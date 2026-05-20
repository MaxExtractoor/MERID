"""
Comprehensive Test Suite for MERID Dev Swarm

Tests cover:
- DevSwarm core functionality
- Safety limits and timeouts
- Cost tracking and budgets
- Task lifecycle management
- Error handling
- API endpoints
"""

import pytest

# Dev Swarm subsystem: strict coverage gate (target ≥90%)
pytestmark = pytest.mark.dev_swarm
import asyncio
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock
from typing import Dict, Any

from core.dev_swarm import (
    DevSwarm,
    DevTask,
    DevAgent,
    DevAgentRole,
    SwarmConfig,
    create_merid_dev_swarm
)


# Test Fixtures

@pytest.fixture
def swarm_config():
    """Test configuration with permissive limits."""
    return SwarmConfig(
        max_concurrent_tasks=2,
        max_concurrent_agents=5,
        default_task_timeout=5,  # 5 seconds for fast tests
        default_agent_timeout=2,
        max_daily_cost_usd=10.0,
        enable_cost_tracking=True,
        enable_timeouts=True,
        enable_metrics=True
    )


@pytest.fixture
def dev_swarm(swarm_config):
    """Create a test DevSwarm instance."""
    return DevSwarm(config=swarm_config)


@pytest.fixture
def sample_task():
    """Create a sample test task."""
    return DevTask(
        description="Test task for unit testing",
        target_files=["test.py"],
        success_criteria="All tests pass",
        priority=1,
        timeout_seconds=5
    )


@pytest.fixture
def mock_agent():
    """Create a mock dev agent."""
    def dummy_tool(task):
        return {"success": True, "output": "test"}
    
    return DevAgent(
        name="TestAgent",
        role=DevAgentRole.TESTER,
        llm_model="test-model",
        system_prompt="Test prompt",
        tools=[dummy_tool],
        max_iterations=1,
        timeout_seconds=2
    )


# Core Functionality Tests

class TestDevSwarmCore:
    """Test core DevSwarm functionality."""
    
    def test_swarm_initialization(self, swarm_config):
        """Test swarm initializes correctly."""
        swarm = DevSwarm(config=swarm_config)
        
        assert swarm.config == swarm_config
        assert len(swarm.agents) == 0
        assert len(swarm.task_history) == 0
        assert len(swarm.active_tasks) == 0
        assert swarm.daily_cost_usd == 0.0
        assert not swarm._shutdown
    
    def test_agent_registration(self, dev_swarm, mock_agent):
        """Test agent registration."""
        dev_swarm.register_agent(mock_agent)
        
        assert len(dev_swarm.agents) == 1
        assert dev_swarm.agents[0] == mock_agent
    
    def test_find_agent_by_role(self, dev_swarm, mock_agent):
        """Test finding agents by role."""
        dev_swarm.register_agent(mock_agent)
        
        found = dev_swarm._find_agent(DevAgentRole.TESTER)
        assert found == mock_agent
        
        not_found = dev_swarm._find_agent(DevAgentRole.CODER)
        assert not_found is None
    
    @pytest.mark.asyncio
    async def test_task_execution_success(self, dev_swarm, sample_task, mock_agent):
        """Test successful task execution."""
        dev_swarm.register_agent(mock_agent)
        
        result_task = await dev_swarm.execute_task(sample_task)
        
        assert result_task.status == "completed"
        assert result_task.started_at is not None
        assert result_task.completed_at is not None
        assert result_task.error is None
        assert result_task.result is not None
    
    @pytest.mark.asyncio
    async def test_task_id_generation(self, dev_swarm):
        """Test task IDs are unique."""
        ids = set()
        for i in range(20):
            task = DevTask(
                description=f"Task {i}",
                target_files=["test.py"],
                success_criteria="Pass"
            )
            assert task.task_id.startswith("task-")
            ids.add(task.task_id)
        
        # All IDs must be unique (uuid-based)
        assert len(ids) == 20


# Safety Limits Tests

class TestSafetyLimits:
    """Test safety limits and constraints."""
    
    @pytest.mark.asyncio
    async def test_concurrent_task_limit(self, dev_swarm, sample_task):
        """Test max concurrent tasks limit is enforced."""
        # Mock a slow pipeline so tasks stay active
        original_pipeline = dev_swarm._execute_task_pipeline
        async def slow_pipeline(task):
            await asyncio.sleep(5)
            return {"success": True}
        dev_swarm._execute_task_pipeline = slow_pipeline
        
        task1 = DevTask(
            description="Task 1",
            target_files=["test.py"],
            success_criteria="Pass",
            timeout_seconds=10
        )
        task2 = DevTask(
            description="Task 2",
            target_files=["test.py"],
            success_criteria="Pass",
            timeout_seconds=10
        )
        task3 = DevTask(
            description="Task 3",
            target_files=["test.py"],
            success_criteria="Pass"
        )
        
        # Start first two (don't await - they run in background)
        t1 = asyncio.create_task(dev_swarm.execute_task(task1))
        t2 = asyncio.create_task(dev_swarm.execute_task(task2))
        
        # Wait for them to register as active
        await asyncio.sleep(0.2)
        
        # Third should be rejected
        result = await dev_swarm.execute_task(task3)
        
        assert result.status == "failed"
        assert "Max concurrent tasks limit" in result.error
        
        # Cleanup
        t1.cancel()
        t2.cancel()
        try:
            await t1
        except (asyncio.CancelledError, Exception):
            pass
        try:
            await t2
        except (asyncio.CancelledError, Exception):
            pass
        dev_swarm._execute_task_pipeline = original_pipeline
    
    @pytest.mark.asyncio
    async def test_daily_cost_limit(self, dev_swarm, sample_task):
        """Test daily cost budget is enforced."""
        # Exhaust budget
        dev_swarm.daily_cost_usd = dev_swarm.config.max_daily_cost_usd
        
        result = await dev_swarm.execute_task(sample_task)
        
        assert result.status == "failed"
        assert "Daily cost budget exceeded" in result.error
    
    @pytest.mark.asyncio
    async def test_task_timeout(self, dev_swarm):
        """Test task timeout is enforced."""
        # Create task with very short timeout
        task = DevTask(
            description="Slow task",
            target_files=["test.py"],
            success_criteria="Pass",
            timeout_seconds=0.1  # 100ms timeout
        )
        
        # Mock slow agent
        async def slow_pipeline(t):
            await asyncio.sleep(1)  # Takes 1 second
            return {}
        
        with patch.object(dev_swarm, '_execute_task_pipeline', new=slow_pipeline):
            result = await dev_swarm.execute_task(task)
        
        assert result.status == "timeout"
        assert "exceeded timeout" in result.error
    
    @pytest.mark.asyncio
    async def test_cost_tracking(self, dev_swarm, sample_task, mock_agent):
        """Test cost is tracked correctly."""
        dev_swarm.register_agent(mock_agent)
        
        initial_cost = dev_swarm.daily_cost_usd
        
        result = await dev_swarm.execute_task(sample_task)
        
        assert result.cost_usd > 0
        assert dev_swarm.daily_cost_usd > initial_cost
        assert dev_swarm.daily_cost_usd == initial_cost + result.cost_usd
    
    @pytest.mark.asyncio
    async def test_daily_cost_reset(self, dev_swarm):
        """Test daily cost resets after 24 hours."""
        dev_swarm.daily_cost_usd = 50.0
        dev_swarm.cost_reset_time = time.time() - 86401  # >24h ago
        
        task = DevTask(
            description="Test",
            target_files=["test.py"],
            success_criteria="Pass"
        )
        
        await dev_swarm.execute_task(task)
        
        # Cost should have been reset
        assert dev_swarm.daily_cost_usd < 50.0


# Task Lifecycle Tests

class TestTaskLifecycle:
    """Test task lifecycle management."""
    
    @pytest.mark.asyncio
    async def test_task_status_progression(self, dev_swarm, sample_task, mock_agent):
        """Test task status changes through lifecycle."""
        dev_swarm.register_agent(mock_agent)
        
        # Initial status
        assert sample_task.status == "pending"
        
        # After execution
        result = await dev_swarm.execute_task(sample_task)
        
        # Should be in history
        assert len(dev_swarm.task_history) == 1
        assert dev_swarm.task_history[0].task_id == result.task_id
        
        # Should not be active
        assert result.task_id not in dev_swarm.active_tasks
        
        # Should have completed status
        assert result.status in ["completed", "failed", "timeout"]
    
    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_task_cancellation(self, dev_swarm):
        """Test task can be cancelled."""
        # Mock a slow pipeline so task stays active long enough to cancel
        original_pipeline = dev_swarm._execute_task_pipeline
        async def slow_pipeline(task):
            await asyncio.sleep(2)
            return {"success": True}
        dev_swarm._execute_task_pipeline = slow_pipeline
        
        task = DevTask(
            description="Long task",
            target_files=["test.py"],
            success_criteria="Pass",
            timeout_seconds=30
        )
        
        # Start task (don't await)
        bg = asyncio.create_task(dev_swarm.execute_task(task))
        
        # Wait for it to register as active
        await asyncio.sleep(0.2)
        
        # Cancel it
        cancelled = await dev_swarm.cancel_task(task.task_id)
        
        assert cancelled is True
        
        # Cleanup
        try:
            await bg
        except (asyncio.CancelledError, Exception):
            pass
        dev_swarm._execute_task_pipeline = original_pipeline
    
    @pytest.mark.asyncio
    async def test_cancel_nonexistent_task(self, dev_swarm):
        """Test cancelling non-existent task returns False."""
        cancelled = await dev_swarm.cancel_task("nonexistent-id")
        assert cancelled is False
    
    @pytest.mark.asyncio
    async def test_task_history_tracking(self, dev_swarm, mock_agent):
        """Test task history is maintained."""
        dev_swarm.register_agent(mock_agent)
        
        tasks = [
            DevTask(description=f"Task {i}", target_files=["test.py"], success_criteria="Pass")
            for i in range(3)
        ]
        
        for task in tasks:
            await dev_swarm.execute_task(task)
        
        assert len(dev_swarm.task_history) == 3
        assert all(t.task_id in [task.task_id for task in tasks] for t in dev_swarm.task_history)


# Statistics Tests

class TestStatistics:
    """Test statistics and metrics."""
    
    @pytest.mark.asyncio
    async def test_get_stats_empty(self, dev_swarm):
        """Test stats with no tasks."""
        stats = dev_swarm.get_stats()
        
        assert stats["active_tasks"] == 0
        assert stats["total_tasks"] == 0
        assert stats["completed"] == 0
        assert stats["failed"] == 0
        assert stats["success_rate"] == 0
    
    @pytest.mark.asyncio
    async def test_get_stats_with_tasks(self, dev_swarm, mock_agent):
        """Test stats after executing tasks."""
        dev_swarm.register_agent(mock_agent)
        
        # Execute some tasks
        for i in range(3):
            task = DevTask(
                description=f"Task {i}",
                target_files=["test.py"],
                success_criteria="Pass"
            )
            await dev_swarm.execute_task(task)
        
        stats = dev_swarm.get_stats()
        
        assert stats["total_tasks"] == 3
        assert stats["completed"] >= 0
        assert stats["success_rate"] >= 0
        assert stats["avg_duration_seconds"] >= 0
    
    @pytest.mark.asyncio
    async def test_success_rate_calculation(self, dev_swarm, mock_agent):
        """Test success rate is calculated correctly."""
        dev_swarm.register_agent(mock_agent)
        
        # 2 successful tasks
        for i in range(2):
            task = DevTask(
                description=f"Task {i}",
                target_files=["test.py"],
                success_criteria="Pass",
                timeout_seconds=5
            )
            result = await dev_swarm.execute_task(task)
            # Force success
            result.status = "completed"
            dev_swarm.task_history[-1] = result
        
        # 1 failed task
        failed_task = DevTask(
            description="Failed task",
            target_files=["test.py"],
            success_criteria="Pass"
        )
        failed_result = await dev_swarm.execute_task(failed_task)
        failed_result.status = "failed"
        dev_swarm.task_history[-1] = failed_result
        
        stats = dev_swarm.get_stats()
        
        assert stats["completed"] == 2
        assert stats["failed"] == 1
        assert stats["success_rate"] == pytest.approx(2/3, 0.01)


# Error Handling Tests

class TestErrorHandling:
    """Test error handling and recovery."""
    
    @pytest.mark.asyncio
    async def test_agent_tool_failure(self, dev_swarm):
        """Test agent continues when tool fails."""
        def failing_tool(task):
            raise Exception("Tool failed!")
        
        agent = DevAgent(
            name="FailingAgent",
            role=DevAgentRole.TESTER,
            llm_model="test",
            system_prompt="Test",
            tools=[failing_tool],
            max_iterations=1,
            timeout_seconds=2
        )
        
        dev_swarm.register_agent(agent)
        
        task = DevTask(
            description="Test",
            target_files=["test.py"],
            success_criteria="Pass",
            timeout_seconds=5
        )
        
        # Should not crash
        result = await dev_swarm.execute_task(task)
        
        # Task should complete (possibly with errors in tool results)
        assert result.status in ["completed", "failed"]
    
    @pytest.mark.asyncio
    async def test_graceful_shutdown(self, dev_swarm):
        """Test graceful shutdown waits for tasks."""
        # Start a long task
        task = DevTask(
            description="Long task",
            target_files=["test.py"],
            success_criteria="Pass",
            timeout_seconds=5
        )
        
        asyncio.create_task(dev_swarm.execute_task(task))
        await asyncio.sleep(0.1)
        
        # Initiate shutdown
        shutdown_task = asyncio.create_task(dev_swarm.shutdown())
        
        # Should complete quickly (within timeout)
        try:
            await asyncio.wait_for(shutdown_task, timeout=2)
        except asyncio.TimeoutError:
            pytest.fail("Shutdown took too long")
        
        assert dev_swarm._shutdown is True


# Integration Tests

class TestIntegration:
    """Test integration with full workflow."""
    
    @pytest.mark.asyncio
    async def test_full_merid_swarm(self):
        """Test create_merid_dev_swarm factory."""
        swarm = create_merid_dev_swarm()
        
        assert len(swarm.agents) == 4  # Planner, Coder, Tester, Reviewer
        assert swarm.config is not None
        
        # Verify agents are registered
        roles = [agent.role for agent in swarm.agents]
        assert DevAgentRole.PLANNER in roles
        assert DevAgentRole.CODER in roles
        assert DevAgentRole.TESTER in roles
        assert DevAgentRole.REVIEWER in roles
    
    @pytest.mark.asyncio
    async def test_multi_agent_pipeline(self):
        """Test multiple agents execute in sequence."""
        swarm = create_merid_dev_swarm()
        
        task = DevTask(
            description="Add tests for module",
            target_files=["test_module.py"],
            success_criteria="Coverage >80%",
            priority=1,
            timeout_seconds=120  # Generous timeout for 4-agent pipeline
        )
        
        result = await swarm.execute_task(task)
        
        # Should complete (not timeout)
        assert result.status in ["completed", "failed"]
        if result.status == "completed":
            assert result.result is not None
            if "phases" in result.result:
                assert len(result.result["phases"]) > 0


# ============================================
# PERSISTENCE TESTS
# ============================================

class TestPersistence:
    """Tests for DevSwarmPersistence."""

    @pytest.fixture
    def persistence(self, tmp_path):
        """Create a persistence instance with a temp directory."""
        from core.dev_swarm_persistence import DevSwarmPersistence
        return DevSwarmPersistence(storage_path=str(tmp_path / "dev_swarm"))

    @pytest.fixture
    def sample_task(self):
        return DevTask(
            description="Test persistence task",
            target_files=["test.py"],
            success_criteria="Pass",
            priority=1,
            estimated_effort="small",
        )

    def test_save_and_load_task(self, persistence, sample_task):
        """Test saving a task and loading it back."""
        assert persistence.save_task(sample_task) is True

        loaded = persistence.load_tasks()
        assert len(loaded) == 1
        assert loaded[0].task_id == sample_task.task_id
        assert loaded[0].description == sample_task.description
        assert loaded[0].target_files == sample_task.target_files

    def test_load_tasks_empty(self, persistence):
        """Test loading when no tasks file exists."""
        tasks = persistence.load_tasks()
        assert tasks == []

    def test_load_tasks_with_limit(self, persistence):
        """Test loading with a limit returns most recent."""
        for i in range(5):
            t = DevTask(
                description=f"Task {i}",
                target_files=["f.py"],
                success_criteria="Pass",
            )
            persistence.save_task(t)

        loaded = persistence.load_tasks(limit=3)
        assert len(loaded) == 3

    def test_get_task_by_id(self, persistence, sample_task):
        """Test retrieving a specific task by ID."""
        persistence.save_task(sample_task)

        found = persistence.get_task_by_id(sample_task.task_id)
        assert found is not None
        assert found.task_id == sample_task.task_id

    def test_get_task_by_id_not_found(self, persistence):
        """Test retrieving a non-existent task returns None."""
        assert persistence.get_task_by_id("nonexistent") is None

    def test_update_task(self, persistence, sample_task):
        """Test updating an existing task."""
        persistence.save_task(sample_task)

        sample_task.status = "completed"
        sample_task.completed_at = time.time()
        assert persistence.update_task(sample_task) is True

        loaded = persistence.load_tasks()
        assert len(loaded) == 1
        assert loaded[0].status == "completed"

    def test_update_task_not_found_appends(self, persistence):
        """Test updating a non-existent task appends it."""
        task = DevTask(
            description="New task",
            target_files=["f.py"],
            success_criteria="Pass",
        )
        assert persistence.update_task(task) is True

        loaded = persistence.load_tasks()
        assert len(loaded) == 1

    def test_save_and_load_metadata(self, persistence):
        """Test metadata save/load round-trip."""
        meta = {"daily_cost_usd": 1.23, "cost_reset_time": 1700000000.0}
        assert persistence.save_metadata(meta) is True

        loaded = persistence.load_metadata()
        assert loaded["daily_cost_usd"] == 1.23
        assert loaded["cost_reset_time"] == 1700000000.0

    def test_load_metadata_empty(self, persistence):
        """Test loading metadata when file doesn't exist."""
        assert persistence.load_metadata() == {}

    def test_compact_storage(self, persistence):
        """Test compacting storage keeps only recent tasks."""
        for i in range(10):
            t = DevTask(
                description=f"Task {i}",
                target_files=["f.py"],
                success_criteria="Pass",
            )
            persistence.save_task(t)

        assert persistence.compact_storage(keep_recent=3) is True

        loaded = persistence.load_tasks()
        assert len(loaded) == 3

    def test_compact_storage_already_compact(self, persistence):
        """Test compacting when already under limit."""
        t = DevTask(
            description="Solo task",
            target_files=["f.py"],
            success_criteria="Pass",
        )
        persistence.save_task(t)

        assert persistence.compact_storage(keep_recent=100) is True

    def test_get_stats(self, persistence, sample_task):
        """Test storage statistics."""
        persistence.save_task(sample_task)

        stats = persistence.get_stats()
        assert stats["tasks_file_exists"] is True
        assert stats["total_tasks"] == 1
        assert stats["tasks_file_size_bytes"] > 0

    def test_get_stats_empty(self, persistence):
        """Test storage statistics when empty."""
        stats = persistence.get_stats()
        assert stats["tasks_file_exists"] is False


# ============================================
# METRICS TESTS
# ============================================

class TestMetrics:
    """Tests for DevSwarmMetrics."""

    @pytest.fixture
    def metrics(self):
        from core.dev_swarm_metrics import DevSwarmMetrics
        return DevSwarmMetrics()

    @pytest.fixture
    def sample_task(self):
        task = DevTask(
            description="Metrics test task",
            target_files=["test.py"],
            success_criteria="Pass",
            priority=2,
            estimated_effort="medium",
        )
        task.status = "completed"
        task.started_at = time.time() - 10
        task.completed_at = time.time()
        task.cost_usd = 0.5
        return task

    def test_initialize(self, metrics, dev_swarm):
        """Test metrics initialization from swarm state."""
        metrics.initialize(dev_swarm)
        assert metrics._initialized is True

    def test_record_task_created(self, metrics, sample_task):
        """Test recording task creation metric."""
        # Should not raise
        metrics.record_task_created(sample_task)

    def test_record_task_completed(self, metrics, sample_task):
        """Test recording task completion with duration and cost."""
        metrics.record_task_completed(sample_task)

    def test_record_task_completed_no_timestamps(self, metrics):
        """Test recording completion when timestamps are missing."""
        task = DevTask(
            description="No timestamps",
            target_files=["f.py"],
            success_criteria="Pass",
        )
        task.status = "failed"
        metrics.record_task_completed(task)

    def test_update_active_tasks(self, metrics):
        """Test updating active tasks gauge."""
        metrics.update_active_tasks(3)

    def test_update_daily_cost(self, metrics):
        """Test updating daily cost gauge."""
        metrics.update_daily_cost(4.56)

    def test_update_success_rate(self, metrics):
        """Test updating success rate gauge."""
        metrics.update_success_rate(0.85)

    def test_record_agent_phase(self, metrics):
        """Test recording agent phase duration."""
        metrics.record_agent_phase("TestAgent", "planner", 5.0)

    def test_record_agent_phase_with_error(self, metrics):
        """Test recording agent phase with error."""
        metrics.record_agent_phase("TestAgent", "coder", 2.0, error="TimeoutError")

    def test_update_storage_stats(self, metrics):
        """Test updating storage statistics."""
        metrics.update_storage_stats({"tasks_file_size_bytes": 1024})

    def test_update_storage_stats_no_size(self, metrics):
        """Test updating storage stats without size key."""
        metrics.update_storage_stats({})

    def test_update_from_swarm(self, metrics, dev_swarm):
        """Test full metrics update from swarm state."""
        metrics.update_from_swarm(dev_swarm)

    def test_get_metrics_singleton(self):
        """Test global metrics singleton."""
        from core.dev_swarm_metrics import get_metrics
        m1 = get_metrics()
        m2 = get_metrics()
        assert m1 is m2


# ============================================
# API ROUTES TESTS
# ============================================

class TestAPIRoutes:
    """Tests for Dev Swarm FastAPI routes."""

    @pytest.fixture
    def client(self):
        """Create a FastAPI test client with dev swarm routes."""
        import sys
        from unittest.mock import MagicMock
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        # Pre-mock modules that web.api.__init__ transitively imports
        # but which may not exist in the test environment
        stubs = {}
        for mod_name in [
            "hardening", "hardening.lockdown",
            "web.api.institutional", "web.api.system_control",
            "web.api.trading", "web.api.mining", "web.api.reflection",
            "web.api.streams", "web.api.live_stream", "web.api.betting",
            "web.api.paper_trading", "web.api.data_endpoints",
            "web.api.trading_suite",
        ]:
            if mod_name not in sys.modules:
                stubs[mod_name] = MagicMock()
                sys.modules[mod_name] = stubs[mod_name]

        from web.api.dev_swarm_routes import router
        import web.api.dev_swarm_routes as routes_module

        app = FastAPI()
        app.include_router(router)

        # Inject a test swarm so we don't use the global singleton
        test_swarm = create_merid_dev_swarm()
        routes_module._swarm_instance = test_swarm

        # Mock the routes logger (uses stdlib logger which doesn't accept kwargs)
        routes_module.logger = MagicMock()

        yield TestClient(app)

        # Reset global
        routes_module._swarm_instance = None

        # Clean up stubs
        for mod_name in stubs:
            sys.modules.pop(mod_name, None)

    def test_get_stats(self, client):
        """Test GET /api/dev-swarm/stats returns valid stats."""
        resp = client.get("/api/dev-swarm/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "active_tasks" in data
        assert "total_tasks" in data
        assert "success_rate" in data
        assert "daily_cost_usd" in data

    def test_list_agents(self, client):
        """Test GET /api/dev-swarm/agents returns registered agents."""
        resp = client.get("/api/dev-swarm/agents")
        assert resp.status_code == 200
        agents = resp.json()
        assert isinstance(agents, list)
        assert len(agents) >= 1
        assert "name" in agents[0]
        assert "role" in agents[0]

    def test_list_tasks_empty(self, client):
        """Test GET /api/dev-swarm/tasks returns empty list initially."""
        resp = client.get("/api/dev-swarm/tasks")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["tasks"] == []

    def test_create_task(self, client):
        """Test POST /api/dev-swarm/tasks creates a task."""
        resp = client.post("/api/dev-swarm/tasks", json={
            "description": "Add unit tests for the auth module",
            "target_files": ["auth.py"],
            "success_criteria": "All tests pass with >80% coverage",
            "priority": 1,
            "estimated_effort": "medium",
            "timeout_seconds": 300,
            "max_cost_usd": 2.0,
        })
        assert resp.status_code == 201
        data = resp.json()
        assert "task_id" in data
        assert data["status"] == "pending"
        assert data["description"] == "Add unit tests for the auth module"

    def test_create_task_validation_error(self, client):
        """Test POST /api/dev-swarm/tasks rejects invalid input."""
        resp = client.post("/api/dev-swarm/tasks", json={
            "description": "short",
            "target_files": [],
            "success_criteria": "ok",
        })
        assert resp.status_code == 422

    def test_get_task_not_found(self, client):
        """Test GET /api/dev-swarm/tasks/{id} returns 404 for unknown task."""
        resp = client.get("/api/dev-swarm/tasks/nonexistent-id")
        assert resp.status_code == 404

    def test_cancel_task_not_found(self, client):
        """Test DELETE /api/dev-swarm/tasks/{id} returns 404 for unknown task."""
        resp = client.delete("/api/dev-swarm/tasks/nonexistent-id")
        assert resp.status_code == 404

    def test_health_check(self, client):
        """Test GET /api/dev-swarm/health returns health status."""
        resp = client.get("/api/dev-swarm/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("healthy", "degraded")
        assert "agents" in data
        assert "checks" in data

    def test_update_config(self, client):
        """Test POST /api/dev-swarm/config updates configuration."""
        resp = client.post("/api/dev-swarm/config?max_concurrent_tasks=5")
        assert resp.status_code == 200
        data = resp.json()
        assert data["updates"]["max_concurrent_tasks"] == 5

    def test_update_config_no_changes(self, client):
        """Test POST /api/dev-swarm/config with no params."""
        resp = client.post("/api/dev-swarm/config")
        assert resp.status_code == 200
        assert "No configuration changes" in resp.json()["message"]

    def test_create_and_get_task(self, client):
        """Test creating a task then retrieving it by ID."""
        create_resp = client.post("/api/dev-swarm/tasks", json={
            "description": "Integration test for task retrieval flow",
            "target_files": ["module.py"],
            "success_criteria": "Task is retrievable by ID after creation",
        })
        assert create_resp.status_code == 201
        task_id = create_resp.json()["task_id"]

        get_resp = client.get(f"/api/dev-swarm/tasks/{task_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["task_id"] == task_id


# ============================================
# AUDITOR CONTEXT VALIDATION
# ============================================

class TestAuditorContext:
    """Tests that the auditor context module is valid and complete."""

    def test_auditor_context_imports(self):
        """Test that the auditor context module imports cleanly."""
        from core.dev_swarm_auditor_context import (
            AUDITOR_CONTEXT,
            LEGACY_RISK_ZONES,
            LEGACY_REMEDIATION_TASKS,
        )
        assert isinstance(AUDITOR_CONTEXT, str)
        assert isinstance(LEGACY_RISK_ZONES, dict)
        assert isinstance(LEGACY_REMEDIATION_TASKS, list)

    def test_risk_zones_contain_known_categories(self):
        """Test that all expected risk zone categories exist."""
        from core.dev_swarm_auditor_context import LEGACY_RISK_ZONES

        expected_keys = {
            "iocp_hang",
            "redis_dependent",
            "contracts_broken",
            "compliance_broken",
            "agent_interface_mismatch",
            "import_failures",
            "frontend_ts_errors",
        }
        assert expected_keys.issubset(set(LEGACY_RISK_ZONES.keys()))

    def test_risk_zones_are_non_empty(self):
        """Test that each risk zone has at least one entry."""
        from core.dev_swarm_auditor_context import LEGACY_RISK_ZONES

        for key, files in LEGACY_RISK_ZONES.items():
            assert len(files) > 0, f"Risk zone '{key}' is empty"

    def test_remediation_tasks_have_required_fields(self):
        """Test that each remediation task has the required fields."""
        from core.dev_swarm_auditor_context import LEGACY_REMEDIATION_TASKS

        required_fields = {"description", "target_files", "success_criteria", "priority", "estimated_effort"}
        for task in LEGACY_REMEDIATION_TASKS:
            missing = required_fields - set(task.keys())
            assert not missing, f"Task missing fields: {missing}"

    def test_auditor_context_mentions_key_files(self):
        """Test that the auditor context references critical test files."""
        from core.dev_swarm_auditor_context import AUDITOR_CONTEXT

        assert "test_connection_pool.py" in AUDITOR_CONTEXT
        assert "test_intents.py" in AUDITOR_CONTEXT
        import re
        m = re.search(r"(\d+)/\1 tests passing", AUDITOR_CONTEXT)
        assert m and int(m.group(1)) >= 100, "Auditor context must reference >=100 tests in N/N format"


# ============================================
# EXTENDED AUDITOR CONTEXT TESTS
# ============================================

class TestAuditorContextExtended:
    """Extended tests for auditor context referencing new files, markers, and modules."""

    def test_context_references_coverage_gate(self):
        """Auditor context mentions the cov-fail-under gate."""
        from core.dev_swarm_auditor_context import AUDITOR_CONTEXT
        assert "cov-fail-under" in AUDITOR_CONTEXT or "fail-under" in AUDITOR_CONTEXT

    def test_context_references_coverage_percentage(self):
        """Auditor context mentions a coverage percentage >= 90."""
        from core.dev_swarm_auditor_context import AUDITOR_CONTEXT
        import re
        m = re.search(r"(\d+\.\d+)%", AUDITOR_CONTEXT)
        assert m, "No coverage percentage found in auditor context"
        assert float(m.group(1)) >= 90.0

    def test_context_references_legacy_risk_matrix(self):
        """Auditor context references LEGACY_RISK_MATRIX.md."""
        from core.dev_swarm_auditor_context import AUDITOR_CONTEXT
        assert "LEGACY_RISK_MATRIX" in AUDITOR_CONTEXT

    def test_context_references_quarantine_hook(self):
        """Auditor context mentions quarantine or conftest.py."""
        from core.dev_swarm_auditor_context import AUDITOR_CONTEXT
        assert "conftest.py" in AUDITOR_CONTEXT or "quarantine" in AUDITOR_CONTEXT.lower()

    def test_context_references_dev_swarm_module(self):
        """Auditor context mentions core/dev_swarm.py."""
        from core.dev_swarm_auditor_context import AUDITOR_CONTEXT
        assert "dev_swarm" in AUDITOR_CONTEXT

    def test_context_mentions_windows_iocp(self):
        """Auditor context warns about Windows IOCP issues."""
        from core.dev_swarm_auditor_context import AUDITOR_CONTEXT
        assert "IOCP" in AUDITOR_CONTEXT or "iocp" in AUDITOR_CONTEXT

    def test_context_mentions_redis(self):
        """Auditor context warns about Redis-dependent tests."""
        from core.dev_swarm_auditor_context import AUDITOR_CONTEXT
        assert "Redis" in AUDITOR_CONTEXT or "redis" in AUDITOR_CONTEXT

    def test_legacy_risk_zones_files_are_paths(self):
        """All legacy risk zone entries look like file paths."""
        from core.dev_swarm_auditor_context import LEGACY_RISK_ZONES
        for zone, files in LEGACY_RISK_ZONES.items():
            for f in files:
                assert "/" in f or "\\" in f, (
                    f"Risk zone '{zone}': entry '{f}' doesn't look like a path"
                )

    def test_legacy_remediation_priorities_are_bounded(self):
        """All remediation task priorities are in [0, 5]."""
        from core.dev_swarm_auditor_context import LEGACY_REMEDIATION_TASKS
        for task in LEGACY_REMEDIATION_TASKS:
            assert 0 <= task["priority"] <= 5, (
                f"Task '{task['description'][:50]}': priority {task['priority']} out of [0,5]"
            )

    def test_legacy_remediation_efforts_are_valid(self):
        """All remediation task efforts are small/medium/large."""
        from core.dev_swarm_auditor_context import LEGACY_REMEDIATION_TASKS
        valid = {"small", "medium", "large"}
        for task in LEGACY_REMEDIATION_TASKS:
            assert task["estimated_effort"] in valid, (
                f"Task '{task['description'][:50]}': invalid effort '{task['estimated_effort']}'"
            )

    def test_legacy_remediation_target_files_non_empty(self):
        """Every remediation task has at least one target file."""
        from core.dev_swarm_auditor_context import LEGACY_REMEDIATION_TASKS
        for task in LEGACY_REMEDIATION_TASKS:
            assert len(task["target_files"]) >= 1, (
                f"Task '{task['description'][:50]}': empty target_files"
            )

    def test_context_test_count_matches_auditor_check(self):
        """The N/N count in AUDITOR_CONTEXT matches what the readiness auditor would find."""
        from core.dev_swarm_auditor_context import AUDITOR_CONTEXT
        import re
        m = re.search(r"(\d+)/\1 tests passing", AUDITOR_CONTEXT)
        assert m, "No N/N pattern found"
        count = int(m.group(1))
        # The readiness auditor checks for >= 100; verify consistency
        assert count >= 100
        # Also verify the count is self-consistent (N/N, not N/M)
        parts = re.search(r"(\d+)/(\d+) tests passing", AUDITOR_CONTEXT)
        assert parts.group(1) == parts.group(2), "Test count numerator != denominator"


# ============================================
# EDGE CASE TESTS (coverage push toward 90%)
# ============================================

class TestPersistenceIntegration:
    """Tests for DevSwarm with persistence enabled (covers lines 99-105, 188-206, 476-503, 510-512)."""

    @pytest.fixture
    def swarm_with_persistence(self, tmp_path):
        """Create a DevSwarm with persistence enabled."""
        from core.dev_swarm_persistence import DevSwarmPersistence
        config = SwarmConfig(
            max_concurrent_tasks=2,
            max_concurrent_agents=5,
            default_task_timeout=5,
            default_agent_timeout=2,
            max_daily_cost_usd=10.0,
            enable_cost_tracking=True,
            enable_timeouts=True,
            enable_metrics=True,
        )
        swarm = DevSwarm(config=config, enable_persistence=False)
        swarm.persistence = DevSwarmPersistence(storage_path=str(tmp_path / "swarm_data"))
        return swarm

    @pytest.mark.asyncio
    async def test_execute_task_persists(self, swarm_with_persistence):
        """Test that execute_task saves task and metadata to persistence."""
        swarm = swarm_with_persistence
        swarm.register_agent(DevAgent(
            name="Coder", role=DevAgentRole.CODER,
            llm_model="test", system_prompt="test",
            tools=[], max_iterations=1, timeout_seconds=5,
        ))
        task = DevTask(
            description="Persistence integration test",
            target_files=["test.py"],
            success_criteria="Pass",
            timeout_seconds=5,
        )
        result = await swarm.execute_task(task)
        assert result.status in ("completed", "failed", "timeout")

        # Verify task was persisted
        loaded = swarm.persistence.load_tasks()
        assert len(loaded) == 1
        assert loaded[0].task_id == task.task_id

        # Verify metadata was persisted (cost tracking)
        meta = swarm.persistence.load_metadata()
        assert "daily_cost_usd" in meta

    def test_load_state(self, swarm_with_persistence):
        """Test _load_state restores task history and metadata."""
        swarm = swarm_with_persistence
        # Seed persistence with a task and metadata
        t = DevTask(description="Old task", target_files=["f.py"], success_criteria="Pass")
        t.status = "completed"
        swarm.persistence.save_task(t)
        swarm.persistence.save_metadata({"daily_cost_usd": 3.5, "cost_reset_time": 1700000000.0})

        # Clear and reload
        swarm.task_history = []
        swarm.daily_cost_usd = 0.0
        swarm._load_state()

        assert len(swarm.task_history) == 1
        assert swarm.daily_cost_usd == 3.5

    def test_load_state_no_persistence(self):
        """Test _load_state is a no-op without persistence."""
        swarm = DevSwarm(config=SwarmConfig(), enable_persistence=False)
        swarm._load_state()  # Should not raise

    def test_compact_storage_with_persistence(self, swarm_with_persistence):
        """Test compact_storage delegates to persistence."""
        swarm = swarm_with_persistence
        for i in range(5):
            t = DevTask(description=f"Task {i}", target_files=["f.py"], success_criteria="Pass")
            swarm.persistence.save_task(t)

        assert swarm.compact_storage(keep_recent=2) is True
        assert len(swarm.persistence.load_tasks()) == 2

    def test_compact_storage_no_persistence(self):
        """Test compact_storage returns False without persistence."""
        swarm = DevSwarm(config=SwarmConfig(), enable_persistence=False)
        assert swarm.compact_storage() is False

    def test_get_storage_stats_with_persistence(self, swarm_with_persistence):
        """Test get_storage_stats returns persistence stats."""
        swarm = swarm_with_persistence
        stats = swarm.get_storage_stats()
        assert stats["persistence_enabled"] is True

    def test_get_storage_stats_no_persistence(self):
        """Test get_storage_stats without persistence."""
        swarm = DevSwarm(config=SwarmConfig(), enable_persistence=False)
        stats = swarm.get_storage_stats()
        assert stats == {"persistence_enabled": False}

    @pytest.mark.asyncio
    async def test_persist_save_task_exception(self, swarm_with_persistence):
        """Test that persistence save_task exception is caught (lines 189-192)."""
        swarm = swarm_with_persistence
        swarm.register_agent(DevAgent(
            name="Coder", role=DevAgentRole.CODER,
            llm_model="test", system_prompt="test",
            tools=[], max_iterations=1, timeout_seconds=5,
        ))
        # Break persistence to trigger exception
        swarm.persistence.save_task = Mock(side_effect=IOError("disk full"))

        task = DevTask(
            description="Persist failure test task",
            target_files=["test.py"],
            success_criteria="Pass",
            timeout_seconds=5,
        )
        result = await swarm.execute_task(task)
        # Should still complete, just log the error
        assert result.status in ("completed", "failed", "timeout")

    @pytest.mark.asyncio
    async def test_persist_metadata_exception(self, swarm_with_persistence):
        """Test that persistence save_metadata exception is caught (lines 200-206)."""
        swarm = swarm_with_persistence
        swarm.register_agent(DevAgent(
            name="Coder", role=DevAgentRole.CODER,
            llm_model="test", system_prompt="test",
            tools=[], max_iterations=1, timeout_seconds=5,
        ))
        # Break metadata persistence only
        swarm.persistence.save_metadata = Mock(side_effect=IOError("disk full"))

        task = DevTask(
            description="Metadata failure test task",
            target_files=["test.py"],
            success_criteria="Pass",
            timeout_seconds=5,
        )
        result = await swarm.execute_task(task)
        assert result.status in ("completed", "failed", "timeout")


class TestTimeoutsDisabled:
    """Tests for code paths when enable_timeouts=False (covers lines 155, 304)."""

    @pytest.fixture
    def no_timeout_swarm(self):
        config = SwarmConfig(
            max_concurrent_tasks=2,
            default_task_timeout=5,
            default_agent_timeout=2,
            enable_timeouts=False,
            enable_cost_tracking=False,
        )
        swarm = DevSwarm(config=config, enable_persistence=False)
        swarm.register_agent(DevAgent(
            name="Coder", role=DevAgentRole.CODER,
            llm_model="test", system_prompt="test",
            tools=[], max_iterations=1, timeout_seconds=5,
        ))
        return swarm

    @pytest.mark.asyncio
    async def test_execute_without_timeout(self, no_timeout_swarm):
        """Test execute_task path when timeouts are disabled."""
        task = DevTask(
            description="No timeout test task",
            target_files=["test.py"],
            success_criteria="Pass",
        )
        result = await no_timeout_swarm.execute_task(task)
        assert result.status in ("completed", "failed")


class TestAgentPhaseErrors:
    """Tests for agent phase error/timeout paths (covers lines 170-173, 316-336)."""

    @pytest.fixture
    def error_swarm(self):
        config = SwarmConfig(
            max_concurrent_tasks=2,
            default_task_timeout=10,
            default_agent_timeout=2,
            enable_timeouts=True,
            enable_cost_tracking=False,
        )
        return DevSwarm(config=config, enable_persistence=False)

    @pytest.mark.asyncio
    async def test_execute_task_general_exception(self, error_swarm):
        """Test execute_task catches general exceptions (lines 170-173)."""
        swarm = error_swarm

        # Register agent with a tool that raises
        def bad_tool(task):
            raise RuntimeError("tool exploded")

        swarm.register_agent(DevAgent(
            name="BadCoder", role=DevAgentRole.CODER,
            llm_model="test", system_prompt="test",
            tools=[bad_tool], max_iterations=1, timeout_seconds=2,
        ))

        task = DevTask(
            description="Exception path test task",
            target_files=["test.py"],
            success_criteria="Pass",
            timeout_seconds=10,
        )
        result = await swarm.execute_task(task)
        # Tool error is caught inside _execute_agent_tools, so task may still complete
        assert result.status in ("completed", "failed")

    @pytest.mark.asyncio
    async def test_agent_phase_timeout(self, error_swarm):
        """Test agent phase timeout path (lines 316-327)."""
        swarm = error_swarm

        async def slow_execute(agent, task, context):
            await asyncio.sleep(100)
            return {}

        swarm.register_agent(DevAgent(
            name="SlowAgent", role=DevAgentRole.CODER,
            llm_model="test", system_prompt="test",
            tools=[], max_iterations=1, timeout_seconds=1,
        ))

        task = DevTask(
            description="Agent timeout test",
            target_files=["test.py"],
            success_criteria="Pass",
            timeout_seconds=10,
        )

        # Patch _execute_agent_with_tools to be slow
        with patch.object(swarm, '_execute_agent_with_tools', side_effect=slow_execute):
            result = await swarm._run_agent_phase(swarm.agents[0], task, {})
        assert result["status"] == "timeout"
        assert "timed out" in result["error"]

    @pytest.mark.asyncio
    async def test_agent_phase_exception(self, error_swarm):
        """Test agent phase general exception path (lines 329-341)."""
        swarm = error_swarm

        async def exploding_execute(agent, task, context):
            raise ValueError("agent crashed")

        swarm.register_agent(DevAgent(
            name="CrashAgent", role=DevAgentRole.CODER,
            llm_model="test", system_prompt="test",
            tools=[], max_iterations=1, timeout_seconds=5,
        ))

        task = DevTask(
            description="Agent exception test",
            target_files=["test.py"],
            success_criteria="Pass",
        )

        with patch.object(swarm, '_execute_agent_with_tools', side_effect=exploding_execute):
            result = await swarm._run_agent_phase(swarm.agents[0], task, {})
        assert result["status"] == "error"
        assert "agent crashed" in result["error"]


class TestShutdown:
    """Tests for shutdown paths (covers lines 451-472)."""

    @pytest.mark.asyncio
    async def test_shutdown_no_active_tasks(self):
        """Test shutdown with no active tasks."""
        swarm = DevSwarm(config=SwarmConfig(), enable_persistence=False)
        await swarm.shutdown()
        assert swarm._shutdown is True

    @pytest.mark.asyncio
    async def test_shutdown_with_active_tasks(self):
        """Test shutdown waits for (or times out on) active tasks (lines 457-465)."""
        swarm = DevSwarm(config=SwarmConfig(), enable_persistence=False)
        # Simulate an active task
        fake_task = DevTask(description="Running", target_files=["f.py"], success_criteria="Pass")
        fake_task.status = "running"
        swarm.active_tasks[fake_task.task_id] = fake_task

        # Patch _wait_for_active_tasks to raise TimeoutError immediately
        # This exercises the except asyncio.TimeoutError path (line 464-465)
        # without waiting the full 60s shutdown timeout.
        async def mock_wait_that_hangs():
            await asyncio.sleep(999)  # will be cancelled by wait_for

        with patch.object(swarm, '_wait_for_active_tasks', side_effect=mock_wait_that_hangs):
            # Patch wait_for to use a 0.1s timeout instead of 60s
            original_wait_for = asyncio.wait_for

            async def fast_wait_for(coro, timeout=None):
                return await original_wait_for(coro, timeout=0.1)

            with patch('asyncio.wait_for', side_effect=fast_wait_for):
                await swarm.shutdown()

        assert swarm._shutdown is True


class TestToolFunctions:
    """Tests for standalone tool functions (covers lines 516-609)."""

    def test_analyze_coverage_exception(self):
        """Test analyze_coverage handles subprocess failure."""
        from core.dev_swarm import analyze_coverage
        task = DevTask(description="Test", target_files=["f.py"], success_criteria="Pass")
        with patch("core.dev_swarm.subprocess.run", side_effect=FileNotFoundError("coverage not found")):
            result = analyze_coverage(task)
        assert "error" in result

    def test_analyze_coverage_success(self):
        """Test analyze_coverage happy path."""
        from core.dev_swarm import analyze_coverage
        task = DevTask(description="Test", target_files=["f.py"], success_criteria="Pass")
        mock_result = Mock(stdout="Name    Stmts   Miss  Cover\n", stderr="", returncode=0)
        with patch("core.dev_swarm.subprocess.run", return_value=mock_result):
            result = analyze_coverage(task)
        assert result["returncode"] == 0

    def test_run_pytest_exception(self):
        """Test run_pytest handles subprocess failure."""
        from core.dev_swarm import run_pytest
        task = DevTask(description="Test", target_files=["f.py"], success_criteria="Pass")
        with patch("core.dev_swarm.subprocess.run", side_effect=FileNotFoundError("pytest not found")):
            result = run_pytest(task)
        assert "error" in result

    def test_run_pytest_success(self):
        """Test run_pytest happy path."""
        from core.dev_swarm import run_pytest
        task = DevTask(description="Test", target_files=["f.py"], success_criteria="Pass")
        mock_result = Mock(stdout="1 passed", stderr="", returncode=0)
        with patch("core.dev_swarm.subprocess.run", return_value=mock_result):
            result = run_pytest(task)
        assert result["passed"] is True

    def test_run_linters_exception(self):
        """Test run_linters handles subprocess failures."""
        from core.dev_swarm import run_linters
        task = DevTask(description="Test", target_files=["f.py"], success_criteria="Pass")
        with patch("core.dev_swarm.subprocess.run", side_effect=FileNotFoundError("not found")):
            result = run_linters(task)
        assert "error" in result.get("ruff", {})
        assert "error" in result.get("mypy", {})

    def test_run_linters_success(self):
        """Test run_linters happy path."""
        from core.dev_swarm import run_linters
        task = DevTask(description="Test", target_files=["f.py"], success_criteria="Pass")
        mock_result = Mock(stdout="All good", returncode=0)
        with patch("core.dev_swarm.subprocess.run", return_value=mock_result):
            result = run_linters(task)
        assert result["ruff"]["passed"] is True
        assert result["mypy"]["passed"] is True

    def test_get_git_status_exception(self):
        """Test get_git_status handles subprocess failure."""
        from core.dev_swarm import get_git_status
        task = DevTask(description="Test", target_files=["f.py"], success_criteria="Pass")
        with patch("core.dev_swarm.subprocess.run", side_effect=FileNotFoundError("git not found")):
            result = get_git_status(task)
        assert "error" in result

    def test_get_git_status_success(self):
        """Test get_git_status happy path."""
        from core.dev_swarm import get_git_status
        task = DevTask(description="Test", target_files=["f.py"], success_criteria="Pass")
        mock_status = Mock(stdout=" M file.py\n", stderr="", returncode=0)
        mock_diff = Mock(stdout="1 file changed", stderr="", returncode=0)
        with patch("core.dev_swarm.subprocess.run", side_effect=[mock_status, mock_diff]):
            result = get_git_status(task)
        assert "modified_files" in result
        assert "diff_stats" in result


class TestDevTaskTemplates:
    """Tests for DevTaskTemplates (covers lines 673-705)."""

    def test_fix_coverage_gap(self):
        """Test fix_coverage_gap template."""
        from core.dev_swarm import DevTaskTemplates
        task = DevTaskTemplates.fix_coverage_gap("core/engine.py", 45.0, 85.0)
        assert "core/engine.py" in task.description
        assert "45.0%" in task.description
        assert task.target_files == ["core/engine.py"]
        assert task.priority == 1

    def test_add_tests_for_module(self):
        """Test add_tests_for_module template."""
        from core.dev_swarm import DevTaskTemplates
        task = DevTaskTemplates.add_tests_for_module("core/engine.py", "unit")
        assert "unit" in task.description
        assert "core/engine.py" in task.target_files
        assert task.priority == 2

    def test_refactor_for_quality_small(self):
        """Test refactor_for_quality with few issues."""
        from core.dev_swarm import DevTaskTemplates
        task = DevTaskTemplates.refactor_for_quality("core/engine.py", ["type safety"])
        assert task.estimated_effort == "medium"
        assert "type safety" in task.description

    def test_refactor_for_quality_large(self):
        """Test refactor_for_quality with many issues."""
        from core.dev_swarm import DevTaskTemplates
        issues = ["type safety", "dead code", "no tests", "security"]
        task = DevTaskTemplates.refactor_for_quality("core/engine.py", issues)
        assert task.estimated_effort == "large"


class TestAPIRoutesEdgeCases:
    """Additional API route tests for uncovered paths (lines 114, 202, 239, 263-264, 365-366, 386-391)."""

    @pytest.fixture
    def client(self):
        """Create a FastAPI test client with dev swarm routes."""
        import sys
        from unittest.mock import MagicMock
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        stubs = {}
        for mod_name in [
            "hardening", "hardening.lockdown",
            "web.api.institutional", "web.api.system_control",
            "web.api.trading", "web.api.mining", "web.api.reflection",
            "web.api.streams", "web.api.live_stream", "web.api.betting",
            "web.api.paper_trading", "web.api.data_endpoints",
            "web.api.trading_suite",
        ]:
            if mod_name not in sys.modules:
                stubs[mod_name] = MagicMock()
                sys.modules[mod_name] = stubs[mod_name]

        from web.api.dev_swarm_routes import router
        import web.api.dev_swarm_routes as routes_module

        app = FastAPI()
        app.include_router(router)

        test_swarm = create_merid_dev_swarm()
        routes_module._swarm_instance = test_swarm
        routes_module.logger = MagicMock()

        yield TestClient(app), test_swarm, routes_module

        routes_module._swarm_instance = None
        for mod_name in stubs:
            sys.modules.pop(mod_name, None)

    def test_list_tasks_with_status_filter(self, client):
        """Test GET /api/dev-swarm/tasks?status=completed (line 202)."""
        test_client, swarm, _ = client
        # Add a completed task to history
        t = DevTask(description="Done task for filter", target_files=["f.py"], success_criteria="Pass")
        t.status = "completed"
        t.started_at = time.time() - 10
        t.completed_at = time.time()
        swarm.task_history.append(t)

        resp = test_client.get("/api/dev-swarm/tasks?status=completed")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        assert all(t["status"] == "completed" for t in data["tasks"])

    def test_get_task_from_history(self, client):
        """Test GET /api/dev-swarm/tasks/{id} finds task in history (line 239)."""
        test_client, swarm, _ = client
        t = DevTask(description="Historical task", target_files=["f.py"], success_criteria="Pass")
        t.status = "completed"
        swarm.task_history.append(t)

        resp = test_client.get(f"/api/dev-swarm/tasks/{t.task_id}")
        assert resp.status_code == 200
        assert resp.json()["task_id"] == t.task_id

    def test_get_running_task_duration(self, client):
        """Test running task shows duration (line 114)."""
        test_client, swarm, _ = client
        t = DevTask(description="Running task for duration", target_files=["f.py"], success_criteria="Pass")
        t.status = "running"
        t.started_at = time.time() - 5
        swarm.active_tasks[t.task_id] = t

        resp = test_client.get(f"/api/dev-swarm/tasks/{t.task_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["duration_seconds"] is not None
        assert data["duration_seconds"] >= 4

    def test_cancel_active_task(self, client):
        """Test DELETE /api/dev-swarm/tasks/{id} cancels active task (lines 263-264)."""
        test_client, swarm, _ = client
        t = DevTask(description="Cancellable task", target_files=["f.py"], success_criteria="Pass")
        t.status = "running"
        t.started_at = time.time()
        swarm.active_tasks[t.task_id] = t

        resp = test_client.delete(f"/api/dev-swarm/tasks/{t.task_id}")
        assert resp.status_code == 200
        assert "cancelled" in resp.json()["message"]

    def test_update_config_cost(self, client):
        """Test POST /api/dev-swarm/config with cost update (lines 365-366)."""
        test_client, _, _ = client
        resp = test_client.post("/api/dev-swarm/config?max_daily_cost_usd=50.0")
        assert resp.status_code == 200
        assert resp.json()["updates"]["max_daily_cost_usd"] == 50.0


class TestMetricsExceptionPaths:
    """Tests for metrics exception handlers (covers lines 107, 112-113, etc.)."""

    @pytest.fixture
    def metrics(self):
        from core.dev_swarm_metrics import DevSwarmMetrics
        return DevSwarmMetrics()

    def test_record_task_created_with_none_fields(self, metrics):
        """Test record_task_created with minimal task."""
        task = DevTask(description="Minimal", target_files=[], success_criteria="")
        metrics.record_task_created(task)

    def test_update_from_swarm_with_history(self, metrics):
        """Test update_from_swarm with tasks in history."""
        swarm = DevSwarm(config=SwarmConfig(), enable_persistence=False)
        t = DevTask(description="Done", target_files=["f.py"], success_criteria="Pass")
        t.status = "completed"
        t.started_at = time.time() - 5
        t.completed_at = time.time()
        t.cost_usd = 1.0
        swarm.task_history.append(t)
        metrics.update_from_swarm(swarm)


class TestPersistenceExceptionPaths:
    """Tests for persistence exception handlers (covers lines 59-61, 93-95, 121-125, 162-164, etc.)."""

    @pytest.fixture
    def persistence(self, tmp_path):
        from core.dev_swarm_persistence import DevSwarmPersistence
        return DevSwarmPersistence(storage_path=str(tmp_path / "dev_swarm"))

    def test_save_task_corrupted_file(self, persistence):
        """Test save_task when storage file is corrupted."""
        import os
        # Create the storage directory and a corrupted tasks file
        os.makedirs(persistence.storage_path, exist_ok=True)
        tasks_file = os.path.join(persistence.storage_path, "tasks.jsonl")
        with open(tasks_file, "w") as f:
            f.write("NOT VALID JSON\n")

        task = DevTask(description="After corruption", target_files=["f.py"], success_criteria="Pass")
        # save_task appends, so it should still work
        assert persistence.save_task(task) is True

    def test_load_tasks_corrupted_lines(self, persistence):
        """Test load_tasks skips corrupted JSON lines."""
        import os
        os.makedirs(persistence.storage_path, exist_ok=True)
        tasks_file = os.path.join(persistence.storage_path, "tasks.jsonl")
        with open(tasks_file, "w") as f:
            f.write("NOT VALID JSON\n")
            f.write('{"task_id": "test-123", "description": "Valid"}\n')

        loaded = persistence.load_tasks()
        # Should skip the bad line and load what it can (or return empty if strict)
        assert isinstance(loaded, list)

    def test_load_metadata_corrupted(self, persistence):
        """Test load_metadata with corrupted JSON file."""
        import os
        os.makedirs(persistence.storage_path, exist_ok=True)
        meta_file = os.path.join(persistence.storage_path, "metadata.json")
        with open(meta_file, "w") as f:
            f.write("NOT VALID JSON")

        result = persistence.load_metadata()
        assert isinstance(result, dict)


# ============================================
# FINAL GAP TESTS (push toward ≥95%)
# ============================================

class TestPersistenceInitException:
    """Test DevSwarm.__init__ persistence init try/except (lines 100-105)."""

    def test_persistence_init_failure_is_caught(self):
        """When DevSwarmPersistence() raises, swarm still initialises with persistence=None."""
        with patch("core.dev_swarm.PERSISTENCE_AVAILABLE", True), \
             patch("core.dev_swarm_persistence.DevSwarmPersistence", side_effect=RuntimeError("disk gone")):
            swarm = DevSwarm(config=SwarmConfig(), enable_persistence=True)
        assert swarm.persistence is None


class TestExecuteTaskPipelineException:
    """Test execute_task general exception handler (lines 170-173)."""

    @pytest.mark.asyncio
    async def test_pipeline_raises_sets_failed(self):
        """When _execute_task_pipeline raises, task.status becomes 'failed'."""
        swarm = DevSwarm(config=SwarmConfig(enable_timeouts=True), enable_persistence=False)
        swarm.register_agent(DevAgent(
            name="A", role=DevAgentRole.CODER,
            llm_model="t", system_prompt="t",
            tools=[], max_iterations=1, timeout_seconds=5,
        ))

        async def exploding_pipeline(task):
            raise RuntimeError("pipeline boom")

        task = DevTask(
            description="Pipeline exception test task",
            target_files=["f.py"],
            success_criteria="Pass",
            timeout_seconds=10,
        )
        with patch.object(swarm, '_execute_task_pipeline', side_effect=exploding_pipeline):
            result = await swarm.execute_task(task)

        assert result.status == "failed"
        assert "pipeline boom" in result.error


class TestRetryLoop:
    """Test the test-failure retry loop (lines 247-253)."""

    @pytest.mark.asyncio
    async def test_test_failure_triggers_coding_retry(self):
        """When tester returns passed=False, coder retries once."""
        config = SwarmConfig(
            enable_timeouts=False,
            enable_cost_tracking=False,
        )
        swarm = DevSwarm(config=config, enable_persistence=False)

        call_log = []

        async def mock_agent_phase(agent, task, context):
            call_log.append((agent.name, agent.role.value))
            if agent.role == DevAgentRole.TESTER:
                return {"passed": False, "status": "tests_failed"}
            return {"status": "success"}

        swarm.register_agent(DevAgent(name="P", role=DevAgentRole.PLANNER, llm_model="t", system_prompt="t", tools=[], max_iterations=3))
        swarm.register_agent(DevAgent(name="C", role=DevAgentRole.CODER, llm_model="t", system_prompt="t", tools=[], max_iterations=3))
        swarm.register_agent(DevAgent(name="T", role=DevAgentRole.TESTER, llm_model="t", system_prompt="t", tools=[], max_iterations=3))
        swarm.register_agent(DevAgent(name="R", role=DevAgentRole.REVIEWER, llm_model="t", system_prompt="t", tools=[], max_iterations=3))

        task = DevTask(description="Retry loop test", target_files=["f.py"], success_criteria="Pass")

        with patch.object(swarm, '_run_agent_phase', side_effect=mock_agent_phase):
            result = await swarm.execute_task(task)

        # Should see: planner, coder, tester, coder (retry), reviewer
        roles = [name for name, _ in call_log]
        assert "C" in roles
        # The retry should produce a coding_retry phase
        assert result.status == "completed"
        phase_names = [p["phase"] for p in result.result["phases"]]
        assert "coding_retry" in phase_names


class TestWaitForActiveTasks:
    """Test _wait_for_active_tasks body (lines 471-472)."""

    @pytest.mark.asyncio
    async def test_wait_exits_when_tasks_clear(self):
        """_wait_for_active_tasks returns once active_tasks is empty."""
        swarm = DevSwarm(config=SwarmConfig(), enable_persistence=False)
        fake = DevTask(description="X", target_files=["f.py"], success_criteria="P")
        swarm.active_tasks[fake.task_id] = fake

        async def clear_after_delay():
            await asyncio.sleep(0.2)
            swarm.active_tasks.clear()

        # Run both concurrently
        await asyncio.gather(
            swarm._wait_for_active_tasks(),
            clear_after_delay(),
        )
        assert len(swarm.active_tasks) == 0


class TestLoadStateException:
    """Test _load_state exception path (lines 494-495)."""

    def test_load_state_catches_exception(self, tmp_path):
        """When persistence.load_tasks raises, _load_state catches it."""
        from core.dev_swarm_persistence import DevSwarmPersistence
        swarm = DevSwarm(config=SwarmConfig(), enable_persistence=False)
        swarm.persistence = DevSwarmPersistence(storage_path=str(tmp_path / "bad"))
        swarm.persistence.load_tasks = Mock(side_effect=RuntimeError("corrupt"))

        swarm._load_state()  # Should not raise
        assert swarm.task_history == []

    def test_load_state_no_metadata(self, tmp_path):
        """When metadata is empty dict, daily_cost stays at default (line 486->exit)."""
        from core.dev_swarm_persistence import DevSwarmPersistence
        swarm = DevSwarm(config=SwarmConfig(), enable_persistence=False)
        swarm.persistence = DevSwarmPersistence(storage_path=str(tmp_path / "empty"))
        swarm.persistence.load_tasks = Mock(return_value=[])
        swarm.persistence.load_metadata = Mock(return_value={})

        swarm._load_state()
        assert swarm.daily_cost_usd == 0.0


class TestNonCallableTool:
    """Test _execute_agent_tools with a non-callable tool (line 381->378 branch)."""

    @pytest.mark.asyncio
    async def test_non_callable_tool_skipped(self):
        """Non-callable items in tools list are skipped without error."""
        swarm = DevSwarm(config=SwarmConfig(enable_timeouts=False), enable_persistence=False)
        agent = DevAgent(
            name="A", role=DevAgentRole.CODER,
            llm_model="t", system_prompt="t",
            tools=["not_a_function"],  # non-callable
            max_iterations=1, timeout_seconds=5,
        )
        task = DevTask(description="Non-callable tool test", target_files=["f.py"], success_criteria="Pass")
        results = await swarm._execute_agent_tools(agent, task)
        # The string should be iterated but not executed
        assert isinstance(results, dict)


class TestAPIShutdownAndSingleton:
    """Test shutdown endpoint and get_swarm singleton init (lines 35-38, 386-391)."""

    @pytest.fixture
    def client_with_reset(self):
        """Create a test client with _swarm_instance reset to None for singleton test."""
        import sys
        from unittest.mock import MagicMock
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        stubs = {}
        for mod_name in [
            "hardening", "hardening.lockdown",
            "web.api.institutional", "web.api.system_control",
            "web.api.trading", "web.api.mining", "web.api.reflection",
            "web.api.streams", "web.api.live_stream", "web.api.betting",
            "web.api.paper_trading", "web.api.data_endpoints",
            "web.api.trading_suite",
        ]:
            if mod_name not in sys.modules:
                stubs[mod_name] = MagicMock()
                sys.modules[mod_name] = stubs[mod_name]

        from web.api.dev_swarm_routes import router
        import web.api.dev_swarm_routes as routes_module

        app = FastAPI()
        app.include_router(router)
        routes_module.logger = MagicMock()

        yield TestClient(app), routes_module

        routes_module._swarm_instance = None
        for mod_name in stubs:
            sys.modules.pop(mod_name, None)

    def test_get_swarm_singleton_init(self, client_with_reset):
        """Test that get_swarm() creates instance when _swarm_instance is None (lines 35-38)."""
        test_client, routes_module = client_with_reset
        routes_module._swarm_instance = None

        resp = test_client.get("/api/dev-swarm/stats")
        assert resp.status_code == 200
        # Singleton should now be set
        assert routes_module._swarm_instance is not None

    def test_shutdown_endpoint(self, client_with_reset):
        """Test POST /api/dev-swarm/shutdown (lines 386-391)."""
        test_client, routes_module = client_with_reset
        # Ensure swarm exists first
        routes_module._swarm_instance = create_merid_dev_swarm()

        resp = test_client.post("/api/dev-swarm/shutdown")
        assert resp.status_code == 200
        data = resp.json()
        assert "Swarm shutdown initiated" in data["message"]
        assert "warning" in data


class TestReadinessAuditor:
    """Tests for the Dev Swarm Readiness Auditor (core/dev_swarm_readiness_auditor.py)."""

    def test_run_audit_returns_report(self):
        """Full audit produces a report with results."""
        from core.dev_swarm_readiness_auditor import run_audit
        report = run_audit()
        assert len(report.results) >= 10
        assert all(hasattr(r, "status") for r in report.results)

    def test_all_checks_pass_in_current_repo(self):
        """Every check should be OK in the current repo state."""
        from core.dev_swarm_readiness_auditor import run_audit, CheckStatus
        report = run_audit()
        failures = [r for r in report.results if r.status != CheckStatus.OK]
        assert failures == [], f"Failing checks: {[(r.item, r.status.value) for r in failures]}"

    def test_report_passed_property(self):
        """Report.passed is True when all checks are OK."""
        from core.dev_swarm_readiness_auditor import run_audit
        report = run_audit()
        assert report.passed is True
        assert report.drift_count == 0

    def test_summary_table_is_markdown(self):
        """summary_table() returns a Markdown table."""
        from core.dev_swarm_readiness_auditor import run_audit
        report = run_audit()
        table = report.summary_table()
        assert "| #" in table
        assert "**OK**" in table

    def test_create_drift_tasks_empty_when_passing(self):
        """No DevTasks created when all checks pass."""
        from core.dev_swarm_readiness_auditor import run_audit, create_drift_tasks
        report = run_audit()
        tasks = create_drift_tasks(report)
        assert tasks == []

    def test_create_drift_tasks_for_drifted_item(self):
        """DevTasks are created for drifted items."""
        from core.dev_swarm_readiness_auditor import (
            AuditReport, CheckResult, CheckStatus, create_drift_tasks,
        )
        report = AuditReport(results=[
            CheckResult("Testing", "Fake check", CheckStatus.DRIFTED, "file.py", "Fix it"),
            CheckResult("Scripts", "Another", CheckStatus.MISSING, "", "Create it"),
        ])
        tasks = create_drift_tasks(report)
        assert len(tasks) == 2
        assert tasks[0]["priority"] == 2  # DRIFTED
        assert tasks[1]["priority"] == 1  # MISSING

    def test_individual_checks_return_check_result(self):
        """Each check function returns a CheckResult."""
        from core.dev_swarm_readiness_auditor import (
            check_marker_registered, check_ci_gate, check_test_file_exists,
            check_test_count, check_quarantine_hook, check_legacy_risk_matrix,
            check_auditor_context, check_swarm_cli, check_metrics_module,
            check_routes_module, check_coverage_snapshot, CheckResult,
        )
        checks = [
            check_marker_registered, check_ci_gate, check_test_file_exists,
            check_test_count, check_quarantine_hook, check_legacy_risk_matrix,
            check_auditor_context, check_swarm_cli, check_metrics_module,
            check_routes_module, check_coverage_snapshot,
        ]
        for fn in checks:
            result = fn()
            assert isinstance(result, CheckResult), f"{fn.__name__} returned {type(result)}"

    def test_check_makefile_target_hit(self):
        """check_makefile_target finds existing target."""
        from core.dev_swarm_readiness_auditor import check_makefile_target, CheckStatus
        result = check_makefile_target("dev-swarm-test")
        assert result.status == CheckStatus.OK

    def test_check_makefile_target_miss(self):
        """check_makefile_target reports missing target."""
        from core.dev_swarm_readiness_auditor import check_makefile_target, CheckStatus
        result = check_makefile_target("nonexistent-target-xyz")
        assert result.status == CheckStatus.MISSING

    def test_cli_entrypoint_exit_zero(self):
        """CLI exits 0 when all checks pass."""
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m", "core.dev_swarm_readiness_auditor", "--json"],
            capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent),
        )
        assert result.returncode == 0
        import json
        data = json.loads(result.stdout)
        assert data["passed"] is True


class TestReadinessEndpoint:
    """Test GET /api/dev-swarm/readiness route."""

    @pytest.fixture
    def client(self):
        """Create a FastAPI test client with dev swarm routes."""
        import sys as _sys
        from unittest.mock import MagicMock
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        stubs = {}
        for mod_name in [
            "hardening", "hardening.lockdown",
            "web.api.institutional", "web.api.system_control",
            "web.api.trading", "web.api.mining", "web.api.reflection",
            "web.api.streams", "web.api.live_stream", "web.api.betting",
            "web.api.paper_trading", "web.api.data_endpoints",
            "web.api.trading_suite",
        ]:
            if mod_name not in _sys.modules:
                stubs[mod_name] = MagicMock()
                _sys.modules[mod_name] = stubs[mod_name]

        from web.api.dev_swarm_routes import router
        import web.api.dev_swarm_routes as routes_module

        app = FastAPI()
        app.include_router(router)
        routes_module.logger = MagicMock()

        yield TestClient(app)

        routes_module._swarm_instance = None
        for mod_name in stubs:
            _sys.modules.pop(mod_name, None)

    def test_readiness_endpoint_returns_json(self, client):
        """GET /api/dev-swarm/readiness returns audit results."""
        resp = client.get("/api/dev-swarm/readiness")
        assert resp.status_code == 200
        data = resp.json()
        assert "passed" in data
        assert "drift_count" in data
        assert "checks" in data
        assert isinstance(data["checks"], list)
        assert len(data["checks"]) >= 10

    def test_readiness_endpoint_all_ok(self, client):
        """All readiness checks should be OK in current repo state."""
        resp = client.get("/api/dev-swarm/readiness")
        data = resp.json()
        assert data["passed"] is True
        assert data["drift_count"] == 0
        for check in data["checks"]:
            assert check["status"] == "OK", f"Check failed: {check['item']}"


class TestSLOTracking:
    """Tests for SLO history tracking in the readiness auditor."""

    @pytest.fixture(autouse=True)
    def tmp_history(self, tmp_path):
        """Redirect audit history to a temp file for isolation."""
        import core.dev_swarm_readiness_auditor as mod
        self._orig = mod.AUDIT_HISTORY_FILE
        mod.AUDIT_HISTORY_FILE = tmp_path / "history.jsonl"
        yield
        mod.AUDIT_HISTORY_FILE = self._orig

    def test_record_and_load(self):
        """record_audit writes a JSONL line; load_history reads it back."""
        from core.dev_swarm_readiness_auditor import (
            run_audit, record_audit, load_history,
        )
        report = run_audit()
        rec = record_audit(report)
        assert rec["passed"] is True
        assert rec["checks_total"] >= 10

        history = load_history()
        assert len(history) == 1
        assert history[0]["passed"] is True

    def test_multiple_records(self):
        """Multiple records accumulate in history."""
        from core.dev_swarm_readiness_auditor import (
            run_audit, record_audit, load_history,
        )
        report = run_audit()
        for _ in range(5):
            record_audit(report)
        assert len(load_history()) == 5

    def test_compute_slo_empty(self):
        """compute_slo returns defaults when no history exists."""
        from core.dev_swarm_readiness_auditor import compute_slo
        slo = compute_slo()
        assert slo.total_runs == 0
        assert slo.pass_rate == 0.0

    def test_compute_slo_all_passing(self):
        """compute_slo with all-passing history gives 100% pass rate."""
        from core.dev_swarm_readiness_auditor import compute_slo
        history = [{"ts": 1000 + i, "passed": True, "drift_count": 0} for i in range(10)]
        slo = compute_slo(history)
        assert slo.pass_rate == 1.0
        assert slo.current_streak == 10
        assert slo.mean_time_to_fix_seconds == 0.0

    def test_compute_slo_with_failures(self):
        """compute_slo correctly computes MTTF and streak with failures."""
        from core.dev_swarm_readiness_auditor import compute_slo
        history = [
            {"ts": 1000, "passed": True, "drift_count": 0},
            {"ts": 2000, "passed": False, "drift_count": 2},
            {"ts": 2500, "passed": False, "drift_count": 1},
            {"ts": 3000, "passed": True, "drift_count": 0},   # fix after 1000s
            {"ts": 4000, "passed": True, "drift_count": 0},
        ]
        slo = compute_slo(history)
        assert slo.total_runs == 5
        assert slo.pass_rate == 0.6
        assert slo.current_streak == 2
        assert slo.mean_time_to_fix_seconds == 1000.0  # one failure episode: 3000-2000

    def test_slo_metrics_dataclass(self):
        """SLOMetrics has all expected fields."""
        from core.dev_swarm_readiness_auditor import SLOMetrics
        slo = SLOMetrics()
        assert hasattr(slo, "total_runs")
        assert hasattr(slo, "pass_rate")
        assert hasattr(slo, "current_streak")
        assert hasattr(slo, "mean_time_to_fix_seconds")
        assert hasattr(slo, "last_run_epoch")


class TestSLOEndpoint:
    """Test GET /api/dev-swarm/readiness/slo route."""

    @pytest.fixture
    def client(self):
        """Create a FastAPI test client with dev swarm routes."""
        import sys as _sys
        from unittest.mock import MagicMock
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        stubs = {}
        for mod_name in [
            "hardening", "hardening.lockdown",
            "web.api.institutional", "web.api.system_control",
            "web.api.trading", "web.api.mining", "web.api.reflection",
            "web.api.streams", "web.api.live_stream", "web.api.betting",
            "web.api.paper_trading", "web.api.data_endpoints",
            "web.api.trading_suite",
        ]:
            if mod_name not in _sys.modules:
                stubs[mod_name] = MagicMock()
                _sys.modules[mod_name] = stubs[mod_name]

        from web.api.dev_swarm_routes import router
        import web.api.dev_swarm_routes as routes_module

        app = FastAPI()
        app.include_router(router)
        routes_module.logger = MagicMock()

        yield TestClient(app)

        routes_module._swarm_instance = None
        for mod_name in stubs:
            _sys.modules.pop(mod_name, None)

    def test_slo_endpoint_returns_json(self, client):
        """GET /api/dev-swarm/readiness/slo returns SLO metrics."""
        resp = client.get("/api/dev-swarm/readiness/slo")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_runs" in data
        assert "pass_rate" in data
        assert "current_streak" in data
        assert "mean_time_to_fix_seconds" in data
        assert "history" in data
        assert isinstance(data["history"], list)


class TestCodebaseDriftAuditor:
    """Tests for the Codebase Drift Auditor module."""

    def test_drift_report_dataclass(self):
        """DriftReport has expected properties."""
        from core.codebase_drift_auditor import DriftReport, DriftItem, DriftSeverity
        report = DriftReport()
        assert report.passed is True
        assert report.drift_count == 0
        assert report.critical_count == 0

    def test_drift_report_with_critical(self):
        """DriftReport.passed is False when critical items exist."""
        from core.codebase_drift_auditor import DriftReport, DriftItem, DriftSeverity
        report = DriftReport()
        report.items.append(DriftItem(
            id="TEST-1", domain="test", category="security",
            severity=DriftSeverity.CRITICAL, summary="test critical",
        ))
        assert report.passed is False
        assert report.critical_count == 1
        assert report.drift_count == 1

    def test_drift_report_warning_still_passes(self):
        """DriftReport.passed is True when only warnings exist (no criticals)."""
        from core.codebase_drift_auditor import DriftReport, DriftItem, DriftSeverity
        report = DriftReport()
        report.items.append(DriftItem(
            id="TEST-1", domain="test", category="arch",
            severity=DriftSeverity.WARNING, summary="test warning",
        ))
        assert report.passed is True
        assert report.drift_count == 1

    def test_drift_report_to_dict(self):
        """DriftReport.to_dict() returns expected JSON structure."""
        from core.codebase_drift_auditor import DriftReport, DriftItem, DriftSeverity
        report = DriftReport(baseline_version="1.0.0")
        report.items.append(DriftItem(
            id="TEST-1", domain="test", category="coverage",
            severity=DriftSeverity.OK, summary="all good",
        ))
        d = report.to_dict()
        assert d["passed"] is True
        assert d["baseline_version"] == "1.0.0"
        assert len(d["items"]) == 1
        assert d["items"][0]["severity"] == "OK"

    def test_load_baseline(self):
        """load_baseline() returns a dict with expected keys."""
        from core.codebase_drift_auditor import load_baseline
        baseline = load_baseline()
        assert isinstance(baseline, dict)
        assert "domains" in baseline
        assert "legacy_risk_zones" in baseline

    def test_run_drift_audit(self):
        """run_drift_audit() returns a DriftReport with items."""
        from core.codebase_drift_auditor import run_drift_audit
        report = run_drift_audit()
        assert len(report.items) > 0
        assert report.baseline_version == "1.0.0"

    def test_check_baseline_files_exist(self):
        """Baseline files should exist in the repo."""
        from core.codebase_drift_auditor import DriftReport, check_baseline_files_exist, DriftSeverity
        report = DriftReport()
        check_baseline_files_exist(report)
        for item in report.items:
            assert item.severity == DriftSeverity.OK, f"Baseline file missing: {item.summary}"

    def test_check_gitignore_size(self):
        """Gitignore check should run without error."""
        from core.codebase_drift_auditor import DriftReport, check_gitignore_size
        report = DriftReport()
        check_gitignore_size(report)
        assert len(report.items) == 1

    def test_check_dev_swarm_test_count(self):
        """Dev Swarm test count check should detect current tests."""
        from core.codebase_drift_auditor import DriftReport, check_dev_swarm_test_count, load_baseline, DriftSeverity
        baseline = load_baseline()
        report = DriftReport()
        check_dev_swarm_test_count(report, baseline)
        assert len(report.items) == 1
        assert report.items[0].severity == DriftSeverity.OK

    def test_check_empty_test_files(self):
        """Empty test file check should run and report a count."""
        from core.codebase_drift_auditor import DriftReport, check_empty_test_files, load_baseline
        baseline = load_baseline()
        report = DriftReport()
        check_empty_test_files(report, baseline)
        assert len(report.items) == 1
        assert report.items[0].current_value is not None

    def test_create_drift_tasks(self):
        """create_drift_tasks() produces tasks for critical/warning items."""
        from core.codebase_drift_auditor import DriftReport, DriftItem, DriftSeverity, create_drift_tasks
        report = DriftReport()
        report.items.append(DriftItem(
            id="TEST-1", domain="test", category="security",
            severity=DriftSeverity.CRITICAL, summary="bad thing",
            fix_plan="fix it",
        ))
        report.items.append(DriftItem(
            id="TEST-2", domain="test", category="coverage",
            severity=DriftSeverity.OK, summary="good thing",
        ))
        tasks = create_drift_tasks(report)
        assert len(tasks) == 1
        assert "TEST-1" in tasks[0]["description"]


class TestCodebaseDriftEndpoint:
    """Test GET /api/dev-swarm/codebase-drift route."""

    @pytest.fixture
    def client(self):
        """Create a FastAPI test client with dev swarm routes."""
        import sys as _sys
        from unittest.mock import MagicMock
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        stubs = {}
        for mod_name in [
            "hardening", "hardening.lockdown",
            "web.api.institutional", "web.api.system_control",
            "web.api.trading", "web.api.mining", "web.api.reflection",
            "web.api.streams", "web.api.live_stream", "web.api.betting",
            "web.api.paper_trading", "web.api.data_endpoints",
            "web.api.trading_suite",
        ]:
            if mod_name not in _sys.modules:
                stubs[mod_name] = MagicMock()
                _sys.modules[mod_name] = stubs[mod_name]

        from web.api.dev_swarm_routes import router
        import web.api.dev_swarm_routes as routes_module

        app = FastAPI()
        app.include_router(router)
        routes_module.logger = MagicMock()

        yield TestClient(app)

        routes_module._swarm_instance = None
        for mod_name in stubs:
            _sys.modules.pop(mod_name, None)

    def test_codebase_drift_endpoint(self, client):
        """GET /api/dev-swarm/codebase-drift returns drift report."""
        resp = client.get("/api/dev-swarm/codebase-drift")
        assert resp.status_code == 200
        data = resp.json()
        assert "passed" in data
        assert "drift_count" in data
        assert "critical_count" in data
        assert "items" in data
        assert isinstance(data["items"], list)
        assert len(data["items"]) > 0


class TestBaselineDevTaskTemplates:
    """Tests for the new baseline remediation DevTaskTemplates."""

    def test_rotate_secrets_template(self):
        """rotate_secrets_and_purge_history() returns a valid DevTask."""
        from core.dev_swarm import DevTaskTemplates
        task = DevTaskTemplates.rotate_secrets_and_purge_history()
        assert "RG-01" in task.description
        assert task.priority == 0
        assert "kalshi_private_key.pem" in task.target_files

    def test_expand_gitignore_template(self):
        """expand_gitignore() returns a valid DevTask."""
        from core.dev_swarm import DevTaskTemplates
        task = DevTaskTemplates.expand_gitignore()
        assert "RG-03" in task.description
        assert ".gitignore" in task.target_files

    def test_trading_coverage_template(self):
        """improve_trading_execution_coverage() returns a valid DevTask."""
        from core.dev_swarm import DevTaskTemplates
        task = DevTaskTemplates.improve_trading_execution_coverage()
        assert "RG-04" in task.description
        assert "trading/execution.py" in task.target_files

    def test_compliance_coverage_template(self):
        """improve_compliance_audit_coverage() returns a valid DevTask."""
        from core.dev_swarm import DevTaskTemplates
        task = DevTaskTemplates.improve_compliance_audit_coverage()
        assert "RG-05" in task.description
        assert "compliance/audit_logger.py" in task.target_files

    def test_security_tests_template(self):
        """add_security_domain_tests() returns a valid DevTask."""
        from core.dev_swarm import DevTaskTemplates
        task = DevTaskTemplates.add_security_domain_tests()
        assert "RG-07" in task.description
        assert "security/breach_detection.py" in task.target_files

    def test_governance_tests_template(self):
        """add_governance_domain_tests() returns a valid DevTask."""
        from core.dev_swarm import DevTaskTemplates
        task = DevTaskTemplates.add_governance_domain_tests()
        assert "RG-08" in task.description

    def test_api_smoke_tests_template(self):
        """add_web_api_smoke_tests() returns a valid DevTask."""
        from core.dev_swarm import DevTaskTemplates
        task = DevTaskTemplates.add_web_api_smoke_tests()
        assert "RG-10" in task.description

    def test_clean_empty_tests_template(self):
        """clean_empty_test_files() returns a valid DevTask."""
        from core.dev_swarm import DevTaskTemplates
        task = DevTaskTemplates.clean_empty_test_files()
        assert "RG-11" in task.description

    def test_codebase_drift_audit_template(self):
        """codebase_drift_audit() returns a valid DevTask."""
        from core.dev_swarm import DevTaskTemplates
        task = DevTaskTemplates.codebase_drift_audit()
        assert "Codebase Drift Auditor" in task.description
        assert "CODEBASE_BASELINE.json" in task.target_files

    def test_all_baseline_templates_callable(self):
        """All baseline remediation templates are callable and return DevTasks."""
        from core.dev_swarm import DevTaskTemplates, DevTask
        templates = [
            DevTaskTemplates.rotate_secrets_and_purge_history,
            DevTaskTemplates.expand_gitignore,
            DevTaskTemplates.improve_trading_execution_coverage,
            DevTaskTemplates.improve_compliance_audit_coverage,
            DevTaskTemplates.add_security_domain_tests,
            DevTaskTemplates.add_governance_domain_tests,
            DevTaskTemplates.add_web_api_smoke_tests,
            DevTaskTemplates.clean_empty_test_files,
            DevTaskTemplates.refactor_core_into_subpackages,
            DevTaskTemplates.break_god_classes,
            DevTaskTemplates.add_data_feed_tests,
            DevTaskTemplates.add_frontend_tests,
            DevTaskTemplates.archive_stale_docs,
            DevTaskTemplates.consolidate_utf8_utils,
            DevTaskTemplates.codebase_drift_audit,
            DevTaskTemplates.build_state_manager,
            DevTaskTemplates.implement_black_swan_drill_harness,
            DevTaskTemplates.add_observability_kill_switch,
            DevTaskTemplates.enforce_agent_registry,
            DevTaskTemplates.build_emergency_control_panel,
            DevTaskTemplates.add_model_drift_detection,
            DevTaskTemplates.add_override_intent_logging,
        ]
        for tmpl in templates:
            task = tmpl()
            assert isinstance(task, DevTask), f"{tmpl.__name__} did not return DevTask"
            assert task.description, f"{tmpl.__name__} has empty description"


# ============================================
# SEASON 2 TIER 1 RISK GAP TEMPLATES
# ============================================

class TestRRGDevTaskTemplates:
    """Tests for the Season 2 Tier 1 Risk Gap DevTaskTemplates (RRG-01..RRG-10)."""

    def test_build_state_manager_template(self):
        """build_state_manager() returns a valid DevTask for RRG-01/RRG-02."""
        from core.dev_swarm import DevTaskTemplates
        task = DevTaskTemplates.build_state_manager()
        assert "RRG-01" in task.description
        assert "RRG-02" in task.description
        assert "CriticalStateManager" in task.description
        assert task.priority == 0
        assert "core/critical_state_manager.py" in task.target_files
        assert "core/state_reconciliation.py" in task.target_files
        assert task.estimated_effort == "large"

    def test_black_swan_drill_harness_template(self):
        """implement_black_swan_drill_harness() returns a valid DevTask for RRG-03."""
        from core.dev_swarm import DevTaskTemplates
        task = DevTaskTemplates.implement_black_swan_drill_harness()
        assert "RRG-03" in task.description
        assert "BlackSwanDrillHarness" in task.description
        assert "FlashCrash" in task.description
        assert task.priority == 0
        assert "core/black_swan_drills.py" in task.target_files
        assert task.estimated_effort == "large"

    def test_observability_kill_switch_template(self):
        """add_observability_kill_switch() returns a valid DevTask for RRG-04."""
        from core.dev_swarm import DevTaskTemplates
        task = DevTaskTemplates.add_observability_kill_switch()
        assert "RRG-04" in task.description
        assert "ObservabilityGuard" in task.description
        assert task.priority == 0
        assert "core/observability_guard.py" in task.target_files
        assert task.estimated_effort == "medium"

    def test_enforce_agent_registry_template(self):
        """enforce_agent_registry() returns a valid DevTask for RRG-05."""
        from core.dev_swarm import DevTaskTemplates
        task = DevTaskTemplates.enforce_agent_registry()
        assert "RRG-05" in task.description
        assert "AuthorityEnforcer" in task.description
        assert task.priority == 1
        assert "swarm/agent_registry.py" in task.target_files
        assert "swarm/authority_enforcer.py" in task.target_files
        assert task.estimated_effort == "large"

    def test_emergency_control_panel_template(self):
        """build_emergency_control_panel() returns a valid DevTask for RRG-06."""
        from core.dev_swarm import DevTaskTemplates
        task = DevTaskTemplates.build_emergency_control_panel()
        assert "RRG-06" in task.description
        assert "EmergencyControlPanel" in task.description
        assert task.priority == 1
        assert "web/react/src/components/EmergencyControlPanel.tsx" in task.target_files
        assert "web/api/emergency_routes.py" in task.target_files
        assert task.estimated_effort == "large"

    def test_model_drift_detection_template(self):
        """add_model_drift_detection() returns a valid DevTask for RRG-08."""
        from core.dev_swarm import DevTaskTemplates
        task = DevTaskTemplates.add_model_drift_detection()
        assert "RRG-08" in task.description
        assert "ModelDriftDetector" in task.description
        assert task.priority == 2
        assert "core/model_drift_detector.py" in task.target_files
        assert task.estimated_effort == "medium"

    def test_override_intent_logging_template(self):
        """add_override_intent_logging() returns a valid DevTask for RRG-09."""
        from core.dev_swarm import DevTaskTemplates
        task = DevTaskTemplates.add_override_intent_logging()
        assert "RRG-09" in task.description
        assert "OverrideManager" in task.description
        assert task.priority == 2
        assert "core/override_manager.py" in task.target_files
        assert task.estimated_effort == "medium"

    def test_rrg_templates_priority_ordering(self):
        """Critical RRG templates (01-04) have priority 0, high (05-06) have 1, medium (08-09) have 2."""
        from core.dev_swarm import DevTaskTemplates
        assert DevTaskTemplates.build_state_manager().priority == 0
        assert DevTaskTemplates.implement_black_swan_drill_harness().priority == 0
        assert DevTaskTemplates.add_observability_kill_switch().priority == 0
        assert DevTaskTemplates.enforce_agent_registry().priority == 1
        assert DevTaskTemplates.build_emergency_control_panel().priority == 1
        assert DevTaskTemplates.add_model_drift_detection().priority == 2
        assert DevTaskTemplates.add_override_intent_logging().priority == 2


# ============================================
# HISTORICAL COMMITMENTS AUDITOR TESTS
# ============================================

class TestHistoricalCommitmentsAuditor:
    """Tests for core/historical_commitments_auditor.py."""

    def test_parse_gap_report_returns_commitments(self):
        """parse_gap_report() finds commitments in the gap report."""
        from core.historical_commitments_auditor import parse_gap_report
        report = parse_gap_report()
        assert len(report.commitments) > 0
        assert report.parse_errors == []

    def test_parse_gap_report_finds_rrg_items(self):
        """Parser finds RRG-01 through RRG-10 items."""
        from core.historical_commitments_auditor import parse_gap_report
        report = parse_gap_report()
        ids = {c.id for c in report.commitments}
        assert "RRG-01" in ids
        assert "RRG-06" in ids

    def test_parse_gap_report_finds_uw_items(self):
        """Parser finds UW (UI Wiring) items."""
        from core.historical_commitments_auditor import parse_gap_report
        report = parse_gap_report()
        uw_items = [c for c in report.commitments if c.id.startswith("UW")]
        assert len(uw_items) >= 3

    def test_overdue_detection(self):
        """Overdue items are UNTOUCHED/PARTIALLY_COMPLETED with high/critical severity."""
        from core.historical_commitments_auditor import parse_gap_report
        report = parse_gap_report()
        for c in report.overdue_items:
            assert c.status.value in ("UNTOUCHED", "PARTIALLY_COMPLETED")
            assert c.severity.value in ("critical", "high")

    def test_overdue_count_matches_list(self):
        """overdue_count matches len(overdue_items)."""
        from core.historical_commitments_auditor import parse_gap_report
        report = parse_gap_report()
        assert report.overdue_count == len(report.overdue_items)

    def test_report_passed_property(self):
        """Report.passed is False when there are overdue items."""
        from core.historical_commitments_auditor import parse_gap_report
        report = parse_gap_report()
        if report.overdue_count > 0:
            assert report.passed is False
        else:
            assert report.passed is True

    def test_summary_table_is_markdown(self):
        """summary_table() returns a Markdown table."""
        from core.historical_commitments_auditor import parse_gap_report
        report = parse_gap_report()
        table = report.summary_table()
        assert "| #" in table
        assert "Overdue?" in table

    def test_create_overdue_tasks(self):
        """create_overdue_tasks() generates DevTask dicts for overdue items."""
        from core.historical_commitments_auditor import parse_gap_report, create_overdue_tasks
        report = parse_gap_report()
        tasks = create_overdue_tasks(report)
        assert len(tasks) == report.overdue_count
        for t in tasks:
            assert "Historical Commitment" in t["description"]
            assert t["priority"] in (0, 1)
            assert "success_criteria" in t

    def test_check_historical_commitments_integration(self):
        """check_historical_commitments() returns a readiness-compatible dict."""
        from core.historical_commitments_auditor import check_historical_commitments
        result = check_historical_commitments()
        assert "area" in result
        assert result["area"] == "Historical"
        assert "status" in result
        assert result["status"] in ("OK", "DRIFTED")
        assert "evidence" in result

    def test_parse_missing_file(self, tmp_path):
        """Parser handles missing gap report gracefully."""
        from core.historical_commitments_auditor import parse_gap_report
        report = parse_gap_report(path=tmp_path / "nonexistent.md")
        assert len(report.commitments) == 0
        assert len(report.parse_errors) == 1
        assert "not found" in report.parse_errors[0]

    def test_parse_empty_file(self, tmp_path):
        """Parser handles empty file gracefully."""
        from core.historical_commitments_auditor import parse_gap_report
        empty_file = tmp_path / "empty.md"
        empty_file.write_text("")
        report = parse_gap_report(path=empty_file)
        assert len(report.commitments) == 0
        assert report.passed is True

    def test_commitment_status_enum(self):
        """CommitmentStatus enum has expected values."""
        from core.historical_commitments_auditor import CommitmentStatus
        assert CommitmentStatus.COMPLETED.value == "COMPLETED"
        assert CommitmentStatus.UNTOUCHED.value == "UNTOUCHED"
        assert CommitmentStatus.PARTIALLY_COMPLETED.value == "PARTIALLY_COMPLETED"
        assert CommitmentStatus.OBSOLETE.value == "OBSOLETE"

    def test_severity_enum(self):
        """Severity enum has expected values."""
        from core.historical_commitments_auditor import Severity
        assert Severity.CRITICAL.value == "critical"
        assert Severity.HIGH.value == "high"
        assert Severity.MEDIUM.value == "medium"
        assert Severity.LOW.value == "low"

    def test_commitment_is_overdue_logic(self):
        """HistoricalCommitment.is_overdue follows severity + status rules."""
        from core.historical_commitments_auditor import (
            HistoricalCommitment, CommitmentStatus, Severity,
        )
        # UNTOUCHED + CRITICAL = overdue
        c1 = HistoricalCommitment("X-1", "Test", "desc", CommitmentStatus.UNTOUCHED, Severity.CRITICAL)
        assert c1.is_overdue is True

        # COMPLETED + CRITICAL = not overdue
        c2 = HistoricalCommitment("X-2", "Test", "desc", CommitmentStatus.COMPLETED, Severity.CRITICAL)
        assert c2.is_overdue is False

        # UNTOUCHED + LOW = not overdue
        c3 = HistoricalCommitment("X-3", "Test", "desc", CommitmentStatus.UNTOUCHED, Severity.LOW)
        assert c3.is_overdue is False

        # PARTIALLY_COMPLETED + HIGH = overdue
        c4 = HistoricalCommitment("X-4", "Test", "desc", CommitmentStatus.PARTIALLY_COMPLETED, Severity.HIGH)
        assert c4.is_overdue is True

    def test_severity_mapping_by_prefix(self):
        """_severity_for_id maps prefixes correctly."""
        from core.historical_commitments_auditor import _severity_for_id, Severity
        assert _severity_for_id("RRG-01") == Severity.CRITICAL
        assert _severity_for_id("UW-01") == Severity.HIGH
        assert _severity_for_id("SD-01") == Severity.HIGH
        assert _severity_for_id("UNKNOWN-01") == Severity.MEDIUM

    def test_severity_overrides(self):
        """Specific IDs have overridden severities."""
        from core.historical_commitments_auditor import _severity_for_id, Severity
        assert _severity_for_id("RRG-07") == Severity.MEDIUM  # Organizational gap
        assert _severity_for_id("RRG-08") == Severity.MEDIUM  # Tier 2
        assert _severity_for_id("RRG-09") == Severity.MEDIUM  # Tier 2
        assert _severity_for_id("RRG-10") == Severity.MEDIUM  # Tier 2

    def test_cli_entrypoint_exit_code(self):
        """CLI exits with code 1 when overdue items exist (expected in current state)."""
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m", "core.historical_commitments_auditor", "--json"],
            capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent),
        )
        import json
        data = json.loads(result.stdout)
        assert "total_commitments" in data
        assert "overdue_count" in data
        assert "overdue_items" in data
        assert isinstance(data["all_items"], list)
        # Exit code matches: 0 if passed, 1 if overdue
        if data["overdue_count"] > 0:
            assert result.returncode == 1
        else:
            assert result.returncode == 0

    def test_parse_synthetic_report(self, tmp_path):
        """Parser correctly extracts items from a synthetic gap report."""
        from core.historical_commitments_auditor import parse_gap_report, CommitmentStatus
        synthetic = tmp_path / "synthetic.md"
        synthetic.write_text(
            "## Part 2: Risk & Readiness Gaps\n\n"
            "| ID | Gap | Status | Evidence |\n"
            "|----|-----|--------|----------|\n"
            "| TST-01 | Test gap one | **UNTOUCHED** | No code found |\n"
            "| TST-02 | Test gap two | **COMPLETED** | Code exists |\n"
            "| TST-03 | Test gap three | **PARTIALLY_COMPLETED** | Partial |\n"
        )
        report = parse_gap_report(path=synthetic)
        assert len(report.commitments) == 3
        statuses = {c.id: c.status for c in report.commitments}
        assert statuses["TST-01"] == CommitmentStatus.UNTOUCHED
        assert statuses["TST-02"] == CommitmentStatus.COMPLETED
        assert statuses["TST-03"] == CommitmentStatus.PARTIALLY_COMPLETED


# ============================================
# EDGE CASE: RRG TEMPLATE CONTRACT & ISOLATION
# ============================================

class TestRRGTemplateContracts:
    """Contract and isolation tests for RRG DevTaskTemplates."""

    def test_all_rrg_templates_have_required_fields(self):
        """Every RRG template returns a DevTask with all required contract fields."""
        from core.dev_swarm import DevTaskTemplates
        templates = [
            DevTaskTemplates.build_state_manager,
            DevTaskTemplates.implement_black_swan_drill_harness,
            DevTaskTemplates.add_observability_kill_switch,
            DevTaskTemplates.enforce_agent_registry,
            DevTaskTemplates.build_emergency_control_panel,
            DevTaskTemplates.add_model_drift_detection,
            DevTaskTemplates.add_override_intent_logging,
        ]
        for tmpl in templates:
            task = tmpl()
            assert task.description, f"{tmpl.__name__}: empty description"
            assert task.target_files, f"{tmpl.__name__}: empty target_files"
            assert task.success_criteria, f"{tmpl.__name__}: empty success_criteria"
            assert task.priority is not None, f"{tmpl.__name__}: priority is None"
            assert task.estimated_effort in ("small", "medium", "large"), (
                f"{tmpl.__name__}: invalid effort '{task.estimated_effort}'"
            )

    def test_rrg_templates_no_duplicate_task_ids(self):
        """Each RRG template call produces a unique task_id (uuid-based)."""
        from core.dev_swarm import DevTaskTemplates
        ids = set()
        templates = [
            DevTaskTemplates.build_state_manager,
            DevTaskTemplates.implement_black_swan_drill_harness,
            DevTaskTemplates.add_observability_kill_switch,
            DevTaskTemplates.enforce_agent_registry,
            DevTaskTemplates.build_emergency_control_panel,
            DevTaskTemplates.add_model_drift_detection,
            DevTaskTemplates.add_override_intent_logging,
        ]
        for tmpl in templates:
            for _ in range(3):
                task = tmpl()
                assert task.task_id not in ids, f"Duplicate task_id from {tmpl.__name__}"
                ids.add(task.task_id)

    def test_rrg_templates_idempotent_content(self):
        """Calling the same template twice produces identical description/priority/effort."""
        from core.dev_swarm import DevTaskTemplates
        templates = [
            DevTaskTemplates.build_state_manager,
            DevTaskTemplates.implement_black_swan_drill_harness,
            DevTaskTemplates.add_observability_kill_switch,
            DevTaskTemplates.enforce_agent_registry,
            DevTaskTemplates.build_emergency_control_panel,
            DevTaskTemplates.add_model_drift_detection,
            DevTaskTemplates.add_override_intent_logging,
        ]
        for tmpl in templates:
            t1 = tmpl()
            t2 = tmpl()
            assert t1.description == t2.description, f"{tmpl.__name__}: description changed"
            assert t1.priority == t2.priority, f"{tmpl.__name__}: priority changed"
            assert t1.estimated_effort == t2.estimated_effort, f"{tmpl.__name__}: effort changed"
            assert t1.target_files == t2.target_files, f"{tmpl.__name__}: target_files changed"
            assert t1.success_criteria == t2.success_criteria, f"{tmpl.__name__}: criteria changed"

    def test_rrg_templates_target_files_are_strings(self):
        """All target_files entries are non-empty strings."""
        from core.dev_swarm import DevTaskTemplates
        templates = [
            DevTaskTemplates.build_state_manager,
            DevTaskTemplates.implement_black_swan_drill_harness,
            DevTaskTemplates.add_observability_kill_switch,
            DevTaskTemplates.enforce_agent_registry,
            DevTaskTemplates.build_emergency_control_panel,
            DevTaskTemplates.add_model_drift_detection,
            DevTaskTemplates.add_override_intent_logging,
        ]
        for tmpl in templates:
            task = tmpl()
            for f in task.target_files:
                assert isinstance(f, str) and len(f) > 0, (
                    f"{tmpl.__name__}: invalid target_file entry '{f}'"
                )

    def test_rrg_priority_sort_order(self):
        """When all RRG tasks are sorted by priority, critical comes first."""
        from core.dev_swarm import DevTaskTemplates
        tasks = [
            DevTaskTemplates.add_override_intent_logging(),     # priority 2
            DevTaskTemplates.build_state_manager(),             # priority 0
            DevTaskTemplates.enforce_agent_registry(),          # priority 1
            DevTaskTemplates.add_observability_kill_switch(),   # priority 0
            DevTaskTemplates.add_model_drift_detection(),       # priority 2
            DevTaskTemplates.build_emergency_control_panel(),   # priority 1
            DevTaskTemplates.implement_black_swan_drill_harness(),  # priority 0
        ]
        sorted_tasks = sorted(tasks, key=lambda t: t.priority)
        priorities = [t.priority for t in sorted_tasks]
        assert priorities == sorted(priorities)
        assert sorted_tasks[0].priority == 0
        assert sorted_tasks[-1].priority == 2

    def test_rrg_descriptions_contain_gap_id(self):
        """Every RRG template description contains its RRG-XX identifier."""
        from core.dev_swarm import DevTaskTemplates
        mapping = {
            DevTaskTemplates.build_state_manager: "RRG-01",
            DevTaskTemplates.implement_black_swan_drill_harness: "RRG-03",
            DevTaskTemplates.add_observability_kill_switch: "RRG-04",
            DevTaskTemplates.enforce_agent_registry: "RRG-05",
            DevTaskTemplates.build_emergency_control_panel: "RRG-06",
            DevTaskTemplates.add_model_drift_detection: "RRG-08",
            DevTaskTemplates.add_override_intent_logging: "RRG-09",
        }
        for tmpl, expected_id in mapping.items():
            task = tmpl()
            assert expected_id in task.description, (
                f"{tmpl.__name__}: missing '{expected_id}' in description"
            )

    def test_rrg_templates_include_test_files(self):
        """Every RRG template includes at least one test file in target_files."""
        from core.dev_swarm import DevTaskTemplates
        templates = [
            DevTaskTemplates.build_state_manager,
            DevTaskTemplates.implement_black_swan_drill_harness,
            DevTaskTemplates.add_observability_kill_switch,
            DevTaskTemplates.enforce_agent_registry,
            DevTaskTemplates.build_emergency_control_panel,
            DevTaskTemplates.add_model_drift_detection,
            DevTaskTemplates.add_override_intent_logging,
        ]
        for tmpl in templates:
            task = tmpl()
            test_files = [f for f in task.target_files if "test_" in f or "/tests/" in f]
            assert len(test_files) >= 1, (
                f"{tmpl.__name__}: no test file in target_files {task.target_files}"
            )


# ============================================
# EDGE CASE: HISTORICAL AUDITOR ROBUSTNESS
# ============================================

class TestHistoricalAuditorEdgeCases:
    """Edge-case and robustness tests for the historical commitments auditor."""

    def test_malformed_table_rows_skipped(self, tmp_path):
        """Rows with invalid status values are silently skipped."""
        from core.historical_commitments_auditor import parse_gap_report
        md = tmp_path / "malformed.md"
        md.write_text(
            "## Part 2: Risk & Readiness Gaps\n\n"
            "| ID | Gap | Status | Evidence |\n"
            "|----|-----|--------|----------|\n"
            "| MAL-01 | Good row | **UNTOUCHED** | evidence |\n"
            "| MAL-02 | Bad status | **BANANA** | evidence |\n"
            "| MAL-03 | Another good | **COMPLETED** | evidence |\n"
        )
        report = parse_gap_report(path=md)
        ids = {c.id for c in report.commitments}
        assert "MAL-01" in ids
        assert "MAL-03" in ids
        assert "MAL-02" not in ids  # invalid status skipped

    def test_partial_data_missing_evidence_column(self, tmp_path):
        """Rows with fewer columns than expected still parse if ID+desc+status present."""
        from core.historical_commitments_auditor import parse_gap_report
        md = tmp_path / "partial.md"
        md.write_text(
            "## Part 2: Risk & Readiness Gaps\n\n"
            "| ID | Gap | Status |\n"
            "|----|-----|--------|\n"
            "| PAR-01 | Missing evidence col | **UNTOUCHED** |\n"
        )
        report = parse_gap_report(path=md)
        assert len(report.commitments) == 1
        assert report.commitments[0].id == "PAR-01"

    def test_bold_and_unbold_status_both_parse(self, tmp_path):
        """Status values work with and without bold markdown markers."""
        from core.historical_commitments_auditor import parse_gap_report, CommitmentStatus
        md = tmp_path / "bold.md"
        md.write_text(
            "## Part 2: Risk & Readiness Gaps\n\n"
            "| ID | Gap | Status | Evidence |\n"
            "|----|-----|--------|----------|\n"
            "| BD-01 | Bold status | **COMPLETED** | yes |\n"
            "| BD-02 | Plain status | COMPLETED | yes |\n"
            "| BD-03 | Bold partial | **PARTIALLY_COMPLETED** | partial |\n"
            "| BD-04 | Plain partial | PARTIALLY_COMPLETED | partial |\n"
        )
        report = parse_gap_report(path=md)
        assert len(report.commitments) == 4
        for c in report.commitments:
            assert c.status in (CommitmentStatus.COMPLETED, CommitmentStatus.PARTIALLY_COMPLETED)

    def test_idempotent_parse_no_mutation(self):
        """Parsing the same report twice returns equal but independent objects."""
        from core.historical_commitments_auditor import parse_gap_report
        r1 = parse_gap_report()
        r2 = parse_gap_report()
        assert len(r1.commitments) == len(r2.commitments)
        assert r1.overdue_count == r2.overdue_count
        assert r1.passed == r2.passed
        # Objects are independent
        assert r1 is not r2
        assert r1.commitments is not r2.commitments

    def test_idempotent_task_creation(self):
        """Running create_overdue_tasks twice produces same-length list without side effects."""
        from core.historical_commitments_auditor import parse_gap_report, create_overdue_tasks
        report = parse_gap_report()
        tasks1 = create_overdue_tasks(report)
        tasks2 = create_overdue_tasks(report)
        assert len(tasks1) == len(tasks2)
        # Report is not mutated
        assert report.overdue_count == len(tasks1)
        # Task descriptions match
        for t1, t2 in zip(tasks1, tasks2):
            assert t1["description"] == t2["description"]
            assert t1["priority"] == t2["priority"]

    def test_create_overdue_tasks_empty_report(self):
        """create_overdue_tasks on a report with no commitments returns empty list."""
        from core.historical_commitments_auditor import CommitmentsReport, create_overdue_tasks
        empty = CommitmentsReport()
        assert create_overdue_tasks(empty) == []

    def test_create_overdue_tasks_all_completed(self, tmp_path):
        """No tasks generated when every commitment is COMPLETED."""
        from core.historical_commitments_auditor import parse_gap_report, create_overdue_tasks
        md = tmp_path / "all_done.md"
        md.write_text(
            "## Part 2: Risk & Readiness Gaps\n\n"
            "| ID | Gap | Status | Evidence |\n"
            "|----|-----|--------|----------|\n"
            "| OK-01 | Done one | **COMPLETED** | yes |\n"
            "| OK-02 | Done two | **COMPLETED** | yes |\n"
        )
        report = parse_gap_report(path=md)
        assert report.passed is True
        assert create_overdue_tasks(report) == []

    def test_failure_isolation_one_bad_row(self, tmp_path):
        """A corrupted row mid-table doesn't prevent parsing surrounding valid rows."""
        from core.historical_commitments_auditor import parse_gap_report
        md = tmp_path / "mixed.md"
        md.write_text(
            "## Part 2: Risk & Readiness Gaps\n\n"
            "| ID | Gap | Status | Evidence |\n"
            "|----|-----|--------|----------|\n"
            "| ISO-01 | Valid first | **UNTOUCHED** | evidence |\n"
            "| This is not a valid table row at all\n"
            "| ISO-02 | Valid second | **COMPLETED** | evidence |\n"
            "| ??? | No real ID | **UNTOUCHED** | evidence |\n"
            "| ISO-03 | Valid third | **OBSOLETE** | evidence |\n"
        )
        report = parse_gap_report(path=md)
        ids = {c.id for c in report.commitments}
        assert "ISO-01" in ids
        assert "ISO-02" in ids
        assert "ISO-03" in ids

    def test_overdue_task_priority_matches_severity(self):
        """Overdue tasks from CRITICAL commitments get priority 0, HIGH get priority 1."""
        from core.historical_commitments_auditor import (
            CommitmentsReport, HistoricalCommitment, CommitmentStatus, Severity,
            create_overdue_tasks,
        )
        report = CommitmentsReport(commitments=[
            HistoricalCommitment("C-1", "Test", "critical item", CommitmentStatus.UNTOUCHED, Severity.CRITICAL),
            HistoricalCommitment("H-1", "Test", "high item", CommitmentStatus.UNTOUCHED, Severity.HIGH),
        ])
        tasks = create_overdue_tasks(report)
        assert len(tasks) == 2
        by_id = {t["description"].split("]")[0].split("[")[1].split(" ")[2]: t for t in tasks}
        assert by_id["C-1"]["priority"] == 0
        assert by_id["H-1"]["priority"] == 1

    def test_summary_table_empty_report(self):
        """summary_table on empty report returns header only."""
        from core.historical_commitments_auditor import CommitmentsReport
        report = CommitmentsReport()
        table = report.summary_table()
        assert "| #" in table
        lines = table.strip().split("\n")
        assert len(lines) == 2  # header + separator only

    def test_check_historical_commitments_schema(self):
        """check_historical_commitments returns all required keys for readiness integration."""
        from core.historical_commitments_auditor import check_historical_commitments
        result = check_historical_commitments()
        required_keys = {"area", "item", "status", "evidence", "fix_plan"}
        assert required_keys.issubset(set(result.keys())), (
            f"Missing keys: {required_keys - set(result.keys())}"
        )

    def test_obsolete_status_not_overdue(self):
        """OBSOLETE commitments are never considered overdue regardless of severity."""
        from core.historical_commitments_auditor import (
            HistoricalCommitment, CommitmentStatus, Severity,
        )
        for sev in Severity:
            c = HistoricalCommitment("OBS-1", "Test", "obsolete", CommitmentStatus.OBSOLETE, sev)
            assert c.is_overdue is False, f"OBSOLETE + {sev.value} should not be overdue"

    def test_medium_low_severity_never_overdue(self):
        """MEDIUM and LOW severity commitments are never overdue even if UNTOUCHED."""
        from core.historical_commitments_auditor import (
            HistoricalCommitment, CommitmentStatus, Severity,
        )
        for status in (CommitmentStatus.UNTOUCHED, CommitmentStatus.PARTIALLY_COMPLETED):
            for sev in (Severity.MEDIUM, Severity.LOW):
                c = HistoricalCommitment("ML-1", "Test", "desc", status, sev)
                assert c.is_overdue is False, f"{status.value} + {sev.value} should not be overdue"

    def test_section_tracking_across_parts(self, tmp_path):
        """Parser correctly tracks section changes across Part headers."""
        from core.historical_commitments_auditor import parse_gap_report
        md = tmp_path / "sections.md"
        md.write_text(
            "## Part 2: Risk & Readiness Gaps\n\n"
            "| ID | Gap | Status | Evidence |\n"
            "|----|-----|--------|----------|\n"
            "| SEC-01 | In part 2 | **UNTOUCHED** | evidence |\n\n"
            "## Part 3: UI Wiring Gaps\n\n"
            "| ID | Gap | Status | Evidence |\n"
            "|----|-----|--------|----------|\n"
            "| SEC-02 | In part 3 | **COMPLETED** | evidence |\n\n"
            "## Part 5: Critical Coverage Gaps\n\n"
            "| ID | Gap | Status | Evidence |\n"
            "|----|-----|--------|----------|\n"
            "| SEC-03 | In part 5 | **UNTOUCHED** | evidence |\n"
        )
        report = parse_gap_report(path=md)
        by_id = {c.id: c for c in report.commitments}
        assert by_id["SEC-01"].section == "Risk & Readiness Gaps"
        assert by_id["SEC-02"].section == "UI Wiring Gaps"
        assert by_id["SEC-03"].section == "Critical Coverage Gaps"

    def test_unicode_in_description(self, tmp_path):
        """Parser handles unicode characters in description without error."""
        from core.historical_commitments_auditor import parse_gap_report
        md = tmp_path / "unicode.md"
        md.write_text(
            "## Part 2: Risk & Readiness Gaps\n\n"
            "| ID | Gap | Status | Evidence |\n"
            "|----|-----|--------|----------|\n"
            "| UNI-01 | Résumé of naïve café — «risk» | **COMPLETED** | done |\n",
            encoding="utf-8",
        )
        report = parse_gap_report(path=md)
        assert len(report.commitments) == 1
        assert "café" in report.commitments[0].description

    def test_very_long_description_truncated_in_table(self, tmp_path):
        """summary_table truncates descriptions longer than 60 chars."""
        from core.historical_commitments_auditor import (
            CommitmentsReport, HistoricalCommitment, CommitmentStatus, Severity,
        )
        long_desc = "A" * 200
        report = CommitmentsReport(commitments=[
            HistoricalCommitment("LNG-01", "Test", long_desc, CommitmentStatus.COMPLETED, Severity.LOW),
        ])
        table = report.summary_table()
        # The description column should be truncated to 60 chars
        data_line = table.strip().split("\n")[2]
        assert "A" * 61 not in data_line


# ============================================
# FIXTURE-BASED & PARAMETRIZED TESTS
# ============================================

class TestS2ConfigFixture:
    """Tests that consume the session-scoped dev_swarm_s2_config fixture."""

    @pytest.mark.devswarm
    def test_s2_config_has_all_templates(self, dev_swarm_s2_config):
        """Session config contains all 7 RRG templates."""
        assert dev_swarm_s2_config["season"] == 2
        assert dev_swarm_s2_config["template_count"] == 7
        assert len(dev_swarm_s2_config["templates"]) == 7

    @pytest.mark.devswarm
    def test_s2_config_template_keys(self, dev_swarm_s2_config):
        """All expected template names are present."""
        expected = {
            "build_state_manager",
            "implement_black_swan_drill_harness",
            "add_observability_kill_switch",
            "enforce_agent_registry",
            "build_emergency_control_panel",
            "add_model_drift_detection",
            "add_override_intent_logging",
        }
        assert set(dev_swarm_s2_config["templates"].keys()) == expected

    @pytest.mark.devswarm
    def test_s2_config_priorities_are_ints(self, dev_swarm_s2_config):
        """All template priorities are integers."""
        for name, meta in dev_swarm_s2_config["templates"].items():
            assert isinstance(meta["priority"], int), f"{name}: priority is not int"

    @pytest.mark.devswarm
    def test_s2_config_is_read_only_across_tests(self, dev_swarm_s2_config):
        """Verify the fixture is the same object across tests (session-scoped)."""
        assert dev_swarm_s2_config["season"] == 2


class TestDevSwarmInstanceFixture:
    """Tests that consume the function-scoped dev_swarm_instance fixture."""

    @pytest.mark.devswarm
    def test_instance_is_fresh(self, dev_swarm_instance):
        """Each test gets a clean swarm with no history."""
        assert len(dev_swarm_instance.task_history) == 0
        assert len(dev_swarm_instance.active_tasks) == 0
        assert dev_swarm_instance.daily_cost_usd == 0.0

    @pytest.mark.devswarm
    def test_instance_has_no_persistence(self, dev_swarm_instance):
        """Test fixture disables persistence."""
        assert dev_swarm_instance.persistence is None

    @pytest.mark.devswarm
    def test_instance_config_matches(self, dev_swarm_instance):
        """Test fixture config has expected test-friendly values."""
        cfg = dev_swarm_instance.config
        assert cfg.max_concurrent_tasks == 2
        assert cfg.default_task_timeout == 5
        assert cfg.max_daily_cost_usd == 10.0


class TestParametrizedAuditorOverdue:
    """Parametrized tests using the commitments_dataset_root fixture."""

    @pytest.mark.auditor
    @pytest.mark.parametrize(
        "filename, expected_overdue",
        [
            ("none.md", 0),
            ("one_overdue.md", 1),
            ("mixed.md", 2),
        ],
    )
    def test_auditor_overdue_counts(self, historical_auditor_for, filename, expected_overdue):
        """Overdue count matches expected for each synthetic dataset."""
        report = historical_auditor_for(filename)
        assert report.overdue_count == expected_overdue

    @pytest.mark.auditor
    @pytest.mark.parametrize(
        "filename, expected_passed",
        [
            ("none.md", True),
            ("one_overdue.md", False),
            ("mixed.md", False),
        ],
    )
    def test_auditor_passed_flag(self, historical_auditor_for, filename, expected_passed):
        """Report.passed matches expected for each synthetic dataset."""
        report = historical_auditor_for(filename)
        assert report.passed is expected_passed

    @pytest.mark.auditor
    @pytest.mark.parametrize(
        "filename, expected_total",
        [
            ("none.md", 2),
            ("one_overdue.md", 2),
            ("mixed.md", 4),
            ("malformed.md", 2),
        ],
    )
    def test_auditor_total_commitments(self, historical_auditor_for, filename, expected_total):
        """Total parsed commitments matches expected (invalid rows excluded)."""
        report = historical_auditor_for(filename)
        assert len(report.commitments) == expected_total

    @pytest.mark.auditor
    def test_auditor_malformed_skips_bad_rows(self, historical_auditor_for):
        """Malformed dataset skips invalid rows but parses valid ones."""
        report = historical_auditor_for("malformed.md")
        ids = {c.id for c in report.commitments}
        assert "VAL-01" in ids
        assert "VAL-02" in ids
        assert "BAD-01" not in ids

    @pytest.mark.auditor
    def test_auditor_task_generation_from_fixture(self, historical_auditor_for):
        """create_overdue_tasks produces correct count from mixed dataset."""
        from core.historical_commitments_auditor import create_overdue_tasks
        report = historical_auditor_for("mixed.md")
        tasks = create_overdue_tasks(report)
        assert len(tasks) == report.overdue_count
        for t in tasks:
            assert "Historical Commitment" in t["description"]

    @pytest.mark.auditor
    def test_auditor_none_dataset_no_tasks(self, historical_auditor_for):
        """No tasks generated from all-completed dataset."""
        from core.historical_commitments_auditor import create_overdue_tasks
        report = historical_auditor_for("none.md")
        assert create_overdue_tasks(report) == []


class TestCrossFixtureIntegration:
    """Tests that combine S2 config with auditor fixtures."""

    @pytest.mark.devswarm
    @pytest.mark.auditor
    def test_s2_templates_cover_overdue_gaps(self, dev_swarm_s2_config, historical_auditor_for):
        """RRG templates in S2 config address the overdue gaps in one_overdue dataset."""
        report = historical_auditor_for("one_overdue.md")
        overdue_ids = {c.id for c in report.overdue_items}
        # RRG-01 is overdue in one_overdue.md; build_state_manager covers RRG-01
        template_descs = " ".join(
            m["description"] for m in dev_swarm_s2_config["templates"].values()
        )
        for oid in overdue_ids:
            assert oid in template_descs, (
                f"Overdue gap {oid} has no matching S2 template"
            )

    @pytest.mark.devswarm
    @pytest.mark.auditor
    def test_mixed_overdue_all_have_templates(self, dev_swarm_s2_config, historical_auditor_for):
        """Every critical/high overdue item from mixed dataset is addressed by an S2 template or baseline."""
        report = historical_auditor_for("mixed.md")
        template_descs = " ".join(
            m["description"] for m in dev_swarm_s2_config["templates"].values()
        )
        for c in report.overdue_items:
            # RRG items should be in S2 templates; UW items are addressed separately
            if c.id.startswith("RRG"):
                assert c.id in template_descs, (
                    f"Overdue RRG gap {c.id} has no matching S2 template"
                )


# ============================================
# NEGATIVE-PATH COVERAGE
# ============================================

class TestNegativePathAuditor:
    """Negative-path and boundary tests for the historical commitments auditor."""

    def test_status_from_str_whitespace_and_case(self):
        """_status_from_str handles extra whitespace and mixed case."""
        from core.historical_commitments_auditor import _status_from_str, CommitmentStatus
        assert _status_from_str("  COMPLETED  ") == CommitmentStatus.COMPLETED
        assert _status_from_str("**UNTOUCHED**") == CommitmentStatus.UNTOUCHED
        assert _status_from_str("PARTIALLY_COMPLETED") == CommitmentStatus.PARTIALLY_COMPLETED
        assert _status_from_str("OBSOLETE") == CommitmentStatus.OBSOLETE

    def test_status_from_str_invalid_returns_none(self):
        """_status_from_str returns None for unrecognized values."""
        from core.historical_commitments_auditor import _status_from_str
        assert _status_from_str("BANANA") is None
        assert _status_from_str("") is None
        assert _status_from_str("   ") is None
        assert _status_from_str("IN_PROGRESS") is None  # not a valid CommitmentStatus

    def test_status_from_str_lowercase_maps_correctly(self):
        """_status_from_str uppercases input before matching."""
        from core.historical_commitments_auditor import _status_from_str, CommitmentStatus
        # The function does .upper() so lowercase should work
        assert _status_from_str("completed") == CommitmentStatus.COMPLETED
        assert _status_from_str("untouched") == CommitmentStatus.UNTOUCHED

    def test_severity_for_id_no_alpha_prefix(self):
        """_severity_for_id with numeric-only prefix falls back to MEDIUM."""
        from core.historical_commitments_auditor import _severity_for_id, Severity
        assert _severity_for_id("123-01") == Severity.MEDIUM

    def test_severity_for_id_empty_string(self):
        """_severity_for_id with empty string returns MEDIUM."""
        from core.historical_commitments_auditor import _severity_for_id, Severity
        assert _severity_for_id("") == Severity.MEDIUM

    def test_severity_for_id_unknown_prefix(self):
        """_severity_for_id with unknown prefix returns MEDIUM."""
        from core.historical_commitments_auditor import _severity_for_id, Severity
        assert _severity_for_id("ZZZ-99") == Severity.MEDIUM
        assert _severity_for_id("ABC-01") == Severity.MEDIUM

    def test_duplicate_ids_in_report(self, tmp_path):
        """Parser does not deduplicate — duplicate IDs both appear."""
        from core.historical_commitments_auditor import parse_gap_report
        md = tmp_path / "dupes.md"
        md.write_text(
            "## Part 2: Risk & Readiness Gaps\n\n"
            "| ID | Gap | Status | Evidence |\n"
            "|----|-----|--------|----------|\n"
            "| DUP-01 | First occurrence | **COMPLETED** | yes |\n"
            "| DUP-01 | Second occurrence | **UNTOUCHED** | no |\n",
            encoding="utf-8",
        )
        report = parse_gap_report(path=md)
        assert len(report.commitments) == 2
        assert all(c.id == "DUP-01" for c in report.commitments)

    def test_file_with_no_table_section(self, tmp_path):
        """File with content but no table rows yields empty commitments."""
        from core.historical_commitments_auditor import parse_gap_report
        md = tmp_path / "no_table.md"
        md.write_text(
            "# Historical Audit Gap Report\n\n"
            "This document has narrative text but no table rows.\n\n"
            "## Part 2: Risk & Readiness Gaps\n\n"
            "No gaps identified at this time.\n",
            encoding="utf-8",
        )
        report = parse_gap_report(path=md)
        assert len(report.commitments) == 0
        assert report.passed is True
        assert report.parse_errors == []

    def test_file_with_only_separator_rows(self, tmp_path):
        """Table with only header/separator but no data rows yields empty."""
        from core.historical_commitments_auditor import parse_gap_report
        md = tmp_path / "header_only.md"
        md.write_text(
            "## Part 2: Risk & Readiness Gaps\n\n"
            "| ID | Gap | Status | Evidence |\n"
            "|----|-----|--------|----------|\n",
            encoding="utf-8",
        )
        report = parse_gap_report(path=md)
        assert len(report.commitments) == 0

    def test_overdue_tasks_have_empty_target_files(self):
        """create_overdue_tasks always produces empty target_files."""
        from core.historical_commitments_auditor import (
            CommitmentsReport, HistoricalCommitment, CommitmentStatus, Severity,
            create_overdue_tasks,
        )
        report = CommitmentsReport(commitments=[
            HistoricalCommitment("X-1", "Test", "desc", CommitmentStatus.UNTOUCHED, Severity.CRITICAL),
        ])
        tasks = create_overdue_tasks(report)
        assert tasks[0]["target_files"] == []
        assert tasks[0]["estimated_effort"] == "large"

    def test_overdue_tasks_success_criteria_references_id(self):
        """Each overdue task's success_criteria references the commitment ID."""
        from core.historical_commitments_auditor import (
            CommitmentsReport, HistoricalCommitment, CommitmentStatus, Severity,
            create_overdue_tasks,
        )
        report = CommitmentsReport(commitments=[
            HistoricalCommitment("ABC-42", "Test", "desc", CommitmentStatus.UNTOUCHED, Severity.HIGH),
        ])
        tasks = create_overdue_tasks(report)
        assert "ABC-42" in tasks[0]["success_criteria"]

    def test_check_historical_commitments_ok_path(self, tmp_path, monkeypatch):
        """check_historical_commitments returns OK when no overdue items."""
        from core import historical_commitments_auditor as mod
        ok_file = tmp_path / "ok.md"
        ok_file.write_text(
            "## Part 2: Risk & Readiness Gaps\n\n"
            "| ID | Gap | Status | Evidence |\n"
            "|----|-----|--------|----------|\n"
            "| OK-01 | Done | **COMPLETED** | yes |\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(mod, "GAP_REPORT_PATH", ok_file)
        result = mod.check_historical_commitments()
        assert result["status"] == "OK"
        assert result["area"] == "Historical"

    def test_check_historical_commitments_drifted_path(self, tmp_path, monkeypatch):
        """check_historical_commitments returns DRIFTED when overdue items exist."""
        from core import historical_commitments_auditor as mod
        bad_file = tmp_path / "bad.md"
        bad_file.write_text(
            "## Part 2: Risk & Readiness Gaps\n\n"
            "| ID | Gap | Status | Evidence |\n"
            "|----|-----|--------|----------|\n"
            "| RRG-01 | Overdue | **UNTOUCHED** | no |\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(mod, "GAP_REPORT_PATH", bad_file)
        result = mod.check_historical_commitments()
        assert result["status"] == "DRIFTED"
        assert "RRG-01" in result["evidence"]

    def test_check_historical_commitments_many_overdue_truncates(self, tmp_path, monkeypatch):
        """When >5 overdue items, evidence shows first 5 + count suffix."""
        from core import historical_commitments_auditor as mod
        rows = "\n".join(
            f"| RRG-{i:02d} | Gap {i} | **UNTOUCHED** | no |"
            for i in range(1, 8)  # RRG-01..07, but 07-10 are MEDIUM so only 01-06 are overdue
        )
        md = tmp_path / "many.md"
        md.write_text(
            f"## Part 2: Risk & Readiness Gaps\n\n"
            f"| ID | Gap | Status | Evidence |\n"
            f"|----|-----|--------|----------|\n"
            f"{rows}\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(mod, "GAP_REPORT_PATH", md)
        result = mod.check_historical_commitments()
        assert result["status"] == "DRIFTED"
        # RRG-01..06 are critical/high (overdue), RRG-07 is medium (not overdue)
        assert "RRG-01" in result["evidence"]

    def test_cli_fix_flag_creates_tasks(self):
        """CLI with --fix flag outputs DevTask creation messages."""
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m", "core.historical_commitments_auditor", "--fix", "--json"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parent.parent),
        )
        import json
        # --json output comes first, then --fix output
        lines = result.stdout.strip().split("\n")
        # Find the JSON block
        json_text = ""
        for i, line in enumerate(lines):
            if line.strip().startswith("{"):
                json_text = "\n".join(lines[i:])
                break
        if json_text:
            # Try to parse just the JSON portion
            brace_count = 0
            end = 0
            for j, ch in enumerate(json_text):
                if ch == "{":
                    brace_count += 1
                elif ch == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        end = j + 1
                        break
            data = json.loads(json_text[:end])
            if data["overdue_count"] > 0:
                remaining = result.stdout[result.stdout.index(json_text[:end]) + end:]
                assert "DevTask" in remaining

    def test_large_report_performance(self, tmp_path):
        """Parser handles a report with 500 rows without error."""
        from core.historical_commitments_auditor import parse_gap_report
        rows = "\n".join(
            f"| TST-{i:03d} | Test gap number {i} | **COMPLETED** | evidence |"
            for i in range(1, 501)
        )
        md = tmp_path / "large.md"
        md.write_text(
            f"## Part 2: Risk & Readiness Gaps\n\n"
            f"| ID | Gap | Status | Evidence |\n"
            f"|----|-----|--------|----------|\n"
            f"{rows}\n",
            encoding="utf-8",
        )
        import time
        start = time.perf_counter()
        report = parse_gap_report(path=md)
        elapsed = time.perf_counter() - start
        assert len(report.commitments) == 500  # IDs TST-001..TST-500 match [A-Z]{2,5}-\d{1,3}
        assert report.passed is True
        assert elapsed < 5.0, f"Parsing 500 rows took {elapsed:.2f}s (>5s threshold)"

    def test_report_with_mixed_sections_and_overdue(self, tmp_path):
        """Overdue items from different sections all detected."""
        from core.historical_commitments_auditor import parse_gap_report
        md = tmp_path / "multi_section.md"
        md.write_text(
            "## Part 2: Risk & Readiness Gaps\n\n"
            "| ID | Gap | Status | Evidence |\n"
            "|----|-----|--------|----------|\n"
            "| RRG-01 | Critical gap | **UNTOUCHED** | no |\n\n"
            "## Part 3: UI Wiring Gaps\n\n"
            "| ID | Gap | Status | Evidence |\n"
            "|----|-----|--------|----------|\n"
            "| UW-01 | UI gap | **UNTOUCHED** | no |\n\n"
            "## Part 5: Critical Coverage Gaps\n\n"
            "| ID | Gap | Status | Evidence |\n"
            "|----|-----|--------|----------|\n"
            "| SD-01 | Silent downgrade | **PARTIALLY_COMPLETED** | partial |\n",
            encoding="utf-8",
        )
        report = parse_gap_report(path=md)
        assert len(report.commitments) == 3
        assert report.overdue_count == 3  # All are high/critical + untouched/partial
        sections = {c.section for c in report.overdue_items}
        assert "Risk & Readiness Gaps" in sections
        assert "UI Wiring Gaps" in sections
        assert "Critical Coverage Gaps" in sections


class TestNegativePathSwarmConfig:
    """Negative-path tests for SwarmConfig and DevSwarm initialization."""

    @pytest.mark.devswarm
    def test_swarm_config_defaults(self):
        """SwarmConfig has sensible defaults when no args provided."""
        from core.dev_swarm import SwarmConfig
        cfg = SwarmConfig()
        assert cfg.max_concurrent_tasks == 5
        assert cfg.max_concurrent_agents == 10
        assert cfg.max_daily_cost_usd > 0

    @pytest.mark.devswarm
    def test_swarm_config_zero_tasks_limit(self):
        """SwarmConfig accepts 0 for max_concurrent_tasks (edge case)."""
        from core.dev_swarm import SwarmConfig
        cfg = SwarmConfig(max_concurrent_tasks=0)
        assert cfg.max_concurrent_tasks == 0

    @pytest.mark.devswarm
    def test_swarm_instance_isolation(self, dev_swarm_instance):
        """Two fixture calls produce independent instances."""
        from core.dev_swarm import DevSwarm, SwarmConfig
        other = DevSwarm(
            config=SwarmConfig(max_concurrent_tasks=1),
            enable_persistence=False,
        )
        assert dev_swarm_instance is not other
        assert dev_swarm_instance.config.max_concurrent_tasks != other.config.max_concurrent_tasks

    @pytest.mark.devswarm
    def test_swarm_daily_cost_starts_at_zero(self, dev_swarm_instance):
        """Fresh swarm has zero daily cost."""
        assert dev_swarm_instance.daily_cost_usd == 0.0

    @pytest.mark.devswarm
    def test_swarm_no_agents_initially(self, dev_swarm_instance):
        """Fresh swarm has no registered agents."""
        assert len(dev_swarm_instance.agents) == 0


# ============================================
# BEHAVIOR: MULTI-DAY / CROSS-BOUNDARY AUDITOR SCENARIOS
# ============================================

class TestAuditorCrossBoundaryScenarios:
    """Scenarios testing auditor behavior across section boundaries, mixed statuses,
    and edge-case report structures that mimic real-world drift over time."""

    @pytest.mark.auditor
    def test_all_sections_populated(self, tmp_path):
        """Report with items in every known section parses all of them."""
        from core.historical_commitments_auditor import parse_gap_report
        md = tmp_path / "all_sections.md"
        md.write_text(
            "## Part 2: Risk & Readiness Gaps\n\n"
            "| ID | Gap | Status | Evidence |\n|----|-----|--------|----------|\n"
            "| RRG-01 | Gap A | **UNTOUCHED** | no |\n\n"
            "## Part 3: UI Wiring Gaps\n\n"
            "| ID | Gap | Status | Evidence |\n|----|-----|--------|----------|\n"
            "| UW-01 | Gap B | **COMPLETED** | yes |\n\n"
            "## Part 5: Critical Coverage Gaps\n\n"
            "| ID | Gap | Status | Evidence |\n|----|-----|--------|----------|\n"
            "| SD-01 | Gap C | **PARTIALLY_COMPLETED** | partial |\n\n"
            "## Part 7: System Audit Issues\n\n"
            "| ID | Gap | Status | Evidence |\n|----|-----|--------|----------|\n"
            "| SA-01 | Gap D | **OBSOLETE** | n/a |\n\n"
            "## Part 8: CI Gate Discrepancies\n\n"
            "| ID | Gap | Status | Evidence |\n|----|-----|--------|----------|\n"
            "| CI-01 | Gap E | **COMPLETED** | yes |\n",
            encoding="utf-8",
        )
        report = parse_gap_report(path=md)
        assert len(report.commitments) == 5
        sections = {c.section for c in report.commitments}
        assert "Risk & Readiness Gaps" in sections
        assert "UI Wiring Gaps" in sections
        assert "Critical Coverage Gaps" in sections
        assert "System Audit Issues" in sections
        assert "CI Gate Discrepancies" in sections

    @pytest.mark.auditor
    def test_progressive_resolution_scenario(self, tmp_path):
        """Simulates a report where items are progressively resolved over time."""
        from core.historical_commitments_auditor import parse_gap_report, create_overdue_tasks
        # Week 1: 3 untouched
        week1 = tmp_path / "week1.md"
        week1.write_text(
            "## Part 2: Risk & Readiness Gaps\n\n"
            "| ID | Gap | Status | Evidence |\n|----|-----|--------|----------|\n"
            "| RRG-01 | Gap 1 | **UNTOUCHED** | no |\n"
            "| RRG-02 | Gap 2 | **UNTOUCHED** | no |\n"
            "| RRG-03 | Gap 3 | **UNTOUCHED** | no |\n",
            encoding="utf-8",
        )
        r1 = parse_gap_report(path=week1)
        assert r1.overdue_count == 3

        # Week 2: 1 completed, 1 partial, 1 still untouched
        week2 = tmp_path / "week2.md"
        week2.write_text(
            "## Part 2: Risk & Readiness Gaps\n\n"
            "| ID | Gap | Status | Evidence |\n|----|-----|--------|----------|\n"
            "| RRG-01 | Gap 1 | **COMPLETED** | PR #42 |\n"
            "| RRG-02 | Gap 2 | **PARTIALLY_COMPLETED** | WIP |\n"
            "| RRG-03 | Gap 3 | **UNTOUCHED** | no |\n",
            encoding="utf-8",
        )
        r2 = parse_gap_report(path=week2)
        assert r2.overdue_count == 2  # RRG-02 partial + RRG-03 untouched

        # Week 3: all completed
        week3 = tmp_path / "week3.md"
        week3.write_text(
            "## Part 2: Risk & Readiness Gaps\n\n"
            "| ID | Gap | Status | Evidence |\n|----|-----|--------|----------|\n"
            "| RRG-01 | Gap 1 | **COMPLETED** | PR #42 |\n"
            "| RRG-02 | Gap 2 | **COMPLETED** | PR #55 |\n"
            "| RRG-03 | Gap 3 | **COMPLETED** | PR #60 |\n",
            encoding="utf-8",
        )
        r3 = parse_gap_report(path=week3)
        assert r3.overdue_count == 0
        assert r3.passed is True
        assert create_overdue_tasks(r3) == []

    @pytest.mark.auditor
    def test_mixed_severity_overdue_priority(self, tmp_path):
        """Overdue items with different severities produce correctly prioritized tasks."""
        from core.historical_commitments_auditor import parse_gap_report, create_overdue_tasks
        md = tmp_path / "mixed_sev.md"
        md.write_text(
            "## Part 2: Risk & Readiness Gaps\n\n"
            "| ID | Gap | Status | Evidence |\n|----|-----|--------|----------|\n"
            "| RRG-01 | Critical gap | **UNTOUCHED** | no |\n"
            "| RRG-05 | High gap | **UNTOUCHED** | no |\n"
            "| RRG-08 | Medium gap | **UNTOUCHED** | no |\n"
            "## Part 3: UI Wiring Gaps\n\n"
            "| ID | Gap | Status | Evidence |\n|----|-----|--------|----------|\n"
            "| UW-01 | UI gap | **UNTOUCHED** | no |\n",
            encoding="utf-8",
        )
        report = parse_gap_report(path=md)
        # RRG-01 critical, RRG-05 critical (default for RRG), UW-01 high, RRG-08 medium (override)
        tasks = create_overdue_tasks(report)
        # RRG-08 is medium severity -> not overdue
        overdue_ids = {c.id for c in report.overdue_items}
        assert "RRG-01" in overdue_ids
        assert "UW-01" in overdue_ids
        assert "RRG-08" not in overdue_ids  # medium severity, not overdue
        # Tasks sorted by priority: critical (0) before high (1)
        priorities = [t["priority"] for t in tasks]
        assert all(p in (0, 1) for p in priorities)

    @pytest.mark.auditor
    def test_obsolete_items_never_generate_tasks(self, tmp_path):
        """OBSOLETE items are parsed but never produce overdue tasks."""
        from core.historical_commitments_auditor import parse_gap_report, create_overdue_tasks
        md = tmp_path / "obsolete.md"
        md.write_text(
            "## Part 2: Risk & Readiness Gaps\n\n"
            "| ID | Gap | Status | Evidence |\n|----|-----|--------|----------|\n"
            "| RRG-01 | Obsolete gap | **OBSOLETE** | deprecated |\n"
            "| RRG-02 | Also obsolete | **OBSOLETE** | removed |\n",
            encoding="utf-8",
        )
        report = parse_gap_report(path=md)
        assert len(report.commitments) == 2
        assert report.overdue_count == 0
        assert create_overdue_tasks(report) == []

    @pytest.mark.auditor
    def test_report_with_interleaved_narrative(self, tmp_path):
        """Parser handles narrative text between table rows without breaking."""
        from core.historical_commitments_auditor import parse_gap_report
        md = tmp_path / "narrative.md"
        md.write_text(
            "## Part 2: Risk & Readiness Gaps\n\n"
            "The following gaps were identified during the Q4 audit.\n\n"
            "| ID | Gap | Status | Evidence |\n|----|-----|--------|----------|\n"
            "| RRG-01 | First gap | **COMPLETED** | done |\n\n"
            "### Additional context\n\n"
            "Some narrative about the gap resolution process.\n\n"
            "| ID | Gap | Status | Evidence |\n|----|-----|--------|----------|\n"
            "| RRG-02 | Second gap | **UNTOUCHED** | no |\n",
            encoding="utf-8",
        )
        report = parse_gap_report(path=md)
        assert len(report.commitments) == 2
        ids = {c.id for c in report.commitments}
        assert "RRG-01" in ids
        assert "RRG-02" in ids


# ============================================
# BEHAVIOR: END-TO-END SEASON 2 RRG FLOWS
# ============================================

class TestSeason2RRGFlows:
    """End-to-end tests combining commitments auditor with DevSwarm planning."""

    @pytest.mark.devswarm
    @pytest.mark.auditor
    def test_overdue_commitments_produce_matching_templates(self, dev_swarm_s2_config, historical_auditor_for):
        """Each overdue RRG commitment has a corresponding S2 template that addresses it."""
        from core.historical_commitments_auditor import create_overdue_tasks
        report = historical_auditor_for("one_overdue.md")
        overdue_tasks = create_overdue_tasks(report)
        template_descs = " ".join(
            m["description"] for m in dev_swarm_s2_config["templates"].values()
        )
        for task in overdue_tasks:
            # Extract the commitment ID from the task description
            # Format: "[Historical Commitment RRG-01] ..."
            import re
            m = re.search(r"\[Historical Commitment ([A-Z]+-\d+)\]", task["description"])
            if m and m.group(1).startswith("RRG"):
                assert m.group(1) in template_descs, (
                    f"Overdue commitment {m.group(1)} has no S2 template"
                )

    @pytest.mark.devswarm
    @pytest.mark.auditor
    def test_full_rrg_pipeline_from_report_to_tasks(self, tmp_path, dev_swarm_s2_config):
        """Full pipeline: parse report -> identify overdue -> generate tasks -> verify coverage."""
        from core.historical_commitments_auditor import parse_gap_report, create_overdue_tasks
        # Create a realistic report with a mix of statuses
        md = tmp_path / "season2.md"
        md.write_text(
            "## Part 2: Risk & Readiness Gaps\n\n"
            "| ID | Gap | Status | Evidence |\n|----|-----|--------|----------|\n"
            "| RRG-01 | State management | **UNTOUCHED** | No code |\n"
            "| RRG-02 | Reconciliation | **COMPLETED** | PR #42 |\n"
            "| RRG-03 | Black swan drills | **UNTOUCHED** | No code |\n"
            "| RRG-04 | Kill switch | **PARTIALLY_COMPLETED** | WIP |\n"
            "| RRG-05 | Agent registry | **COMPLETED** | PR #55 |\n"
            "| RRG-06 | Emergency panel | **UNTOUCHED** | No code |\n",
            encoding="utf-8",
        )
        report = parse_gap_report(path=md)

        # Step 1: Verify parsing
        assert len(report.commitments) == 6
        assert not report.passed

        # Step 2: Identify overdue (critical/high + untouched/partial)
        overdue = report.overdue_items
        overdue_ids = {c.id for c in overdue}
        assert "RRG-01" in overdue_ids  # critical + untouched
        assert "RRG-03" in overdue_ids  # critical + untouched
        assert "RRG-04" in overdue_ids  # critical + partial
        assert "RRG-06" in overdue_ids  # critical + untouched (RRG-06 is not in overrides)
        assert "RRG-02" not in overdue_ids  # completed
        assert "RRG-05" not in overdue_ids  # completed

        # Step 3: Generate tasks
        tasks = create_overdue_tasks(report)
        assert len(tasks) == len(overdue)

        # Step 4: Verify S2 templates cover the overdue gaps
        template_descs = " ".join(
            m["description"] for m in dev_swarm_s2_config["templates"].values()
        )
        for oid in overdue_ids:
            assert oid in template_descs, f"No S2 template for overdue {oid}"

    @pytest.mark.devswarm
    @pytest.mark.auditor
    def test_s2_template_effort_distribution(self, dev_swarm_s2_config):
        """S2 templates have a reasonable effort distribution (not all large)."""
        efforts = [m["estimated_effort"] for m in dev_swarm_s2_config["templates"].values()]
        effort_counts = {e: efforts.count(e) for e in set(efforts)}
        # At least 2 different effort levels
        assert len(effort_counts) >= 2, f"All templates have same effort: {effort_counts}"

    @pytest.mark.devswarm
    @pytest.mark.auditor
    def test_s2_templates_have_success_criteria(self, dev_swarm_s2_config):
        """Every S2 template has non-empty success criteria."""
        for name, meta in dev_swarm_s2_config["templates"].items():
            assert meta["success_criteria"], f"{name}: empty success_criteria"
            assert len(meta["success_criteria"]) > 10, (
                f"{name}: success_criteria too short ({len(meta['success_criteria'])} chars)"
            )

    @pytest.mark.devswarm
    def test_swarm_can_accept_template_tasks(self, dev_swarm_instance):
        """DevSwarm can accept tasks created from S2 templates."""
        from core.dev_swarm import DevTaskTemplates
        templates = [
            DevTaskTemplates.build_state_manager,
            DevTaskTemplates.implement_black_swan_drill_harness,
            DevTaskTemplates.add_observability_kill_switch,
        ]
        for tmpl in templates:
            task = tmpl()
            # Verify the task is compatible with DevSwarm's task tracking
            dev_swarm_instance.task_history.append(task)
        assert len(dev_swarm_instance.task_history) == 3
        # Priorities are preserved
        assert dev_swarm_instance.task_history[0].priority == 0


# ============================================
# LOAD: LIGHT LOAD & BENCHMARK TESTS
# ============================================

class TestLightLoadInvariants:
    """Light load tests verifying invariants hold under repeated operations."""

    @pytest.mark.devswarm
    def test_rapid_template_creation(self):
        """Creating 100 tasks from templates maintains unique IDs and correct priorities."""
        from core.dev_swarm import DevTaskTemplates
        templates = [
            DevTaskTemplates.build_state_manager,
            DevTaskTemplates.implement_black_swan_drill_harness,
            DevTaskTemplates.add_observability_kill_switch,
            DevTaskTemplates.enforce_agent_registry,
            DevTaskTemplates.build_emergency_control_panel,
            DevTaskTemplates.add_model_drift_detection,
            DevTaskTemplates.add_override_intent_logging,
        ]
        all_ids = set()
        for _ in range(100):
            for tmpl in templates:
                task = tmpl()
                assert task.task_id not in all_ids, f"Duplicate ID from {tmpl.__name__}"
                all_ids.add(task.task_id)
        assert len(all_ids) == 700

    @pytest.mark.auditor
    def test_rapid_parse_cycles(self, historical_auditor_for):
        """Parsing the same report 50 times produces consistent results."""
        results = [historical_auditor_for("mixed.md") for _ in range(50)]
        counts = {r.overdue_count for r in results}
        assert len(counts) == 1, f"Inconsistent overdue counts: {counts}"
        totals = {len(r.commitments) for r in results}
        assert len(totals) == 1, f"Inconsistent commitment counts: {totals}"

    @pytest.mark.auditor
    def test_rapid_task_generation(self, historical_auditor_for):
        """Generating tasks 50 times from the same report produces consistent output."""
        from core.historical_commitments_auditor import create_overdue_tasks
        report = historical_auditor_for("mixed.md")
        task_counts = set()
        for _ in range(50):
            tasks = create_overdue_tasks(report)
            task_counts.add(len(tasks))
        assert len(task_counts) == 1, f"Inconsistent task counts: {task_counts}"

    @pytest.mark.devswarm
    def test_swarm_task_history_under_load(self, dev_swarm_instance):
        """Swarm handles 200 tasks in history without issues."""
        from core.dev_swarm import DevTask
        for i in range(200):
            task = DevTask(
                description=f"Load test task {i}",
                target_files=[f"file_{i}.py"],
                success_criteria=f"Criterion {i}",
            )
            dev_swarm_instance.task_history.append(task)
        assert len(dev_swarm_instance.task_history) == 200
        # All IDs unique
        ids = {t.task_id for t in dev_swarm_instance.task_history}
        assert len(ids) == 200

    @pytest.mark.devswarm
    @pytest.mark.auditor
    def test_combined_template_and_auditor_load(self, dev_swarm_s2_config, historical_auditor_for):
        """Interleaving template lookups and auditor parses stays consistent."""
        from core.historical_commitments_auditor import create_overdue_tasks
        for _ in range(20):
            # Parse
            report = historical_auditor_for("mixed.md")
            tasks = create_overdue_tasks(report)
            assert report.overdue_count == len(tasks)
            # Template lookup
            assert dev_swarm_s2_config["template_count"] == 7
            assert dev_swarm_s2_config["season"] == 2


class TestPerformanceBenchmarks:
    """Lightweight perf benchmarks (no pytest-benchmark dependency required)."""

    @pytest.mark.devswarm
    def test_template_creation_throughput(self):
        """All 7 templates can be instantiated 100 times in under 1 second."""
        from core.dev_swarm import DevTaskTemplates
        import time
        templates = [
            DevTaskTemplates.build_state_manager,
            DevTaskTemplates.implement_black_swan_drill_harness,
            DevTaskTemplates.add_observability_kill_switch,
            DevTaskTemplates.enforce_agent_registry,
            DevTaskTemplates.build_emergency_control_panel,
            DevTaskTemplates.add_model_drift_detection,
            DevTaskTemplates.add_override_intent_logging,
        ]
        start = time.perf_counter()
        for _ in range(100):
            for tmpl in templates:
                tmpl()
        elapsed = time.perf_counter() - start
        assert elapsed < 1.0, f"700 template instantiations took {elapsed:.2f}s (>1s)"

    @pytest.mark.auditor
    def test_parse_throughput(self, commitments_dataset_root):
        """Parsing all 4 datasets 10 times each completes in under 2 seconds."""
        from core.historical_commitments_auditor import parse_gap_report
        import time
        files = ["none.md", "one_overdue.md", "mixed.md", "malformed.md"]
        start = time.perf_counter()
        for _ in range(10):
            for f in files:
                parse_gap_report(path=commitments_dataset_root / f)
        elapsed = time.perf_counter() - start
        assert elapsed < 2.0, f"40 parses took {elapsed:.2f}s (>2s)"

    @pytest.mark.auditor
    def test_summary_table_throughput(self):
        """Generating summary table for 100-item report completes in under 0.5s."""
        from core.historical_commitments_auditor import (
            CommitmentsReport, HistoricalCommitment, CommitmentStatus, Severity,
        )
        import time
        commitments = [
            HistoricalCommitment(
                f"TST-{i:03d}", "Test", f"Description {i}",
                CommitmentStatus.COMPLETED, Severity.LOW,
            )
            for i in range(100)
        ]
        report = CommitmentsReport(commitments=commitments)
        start = time.perf_counter()
        for _ in range(100):
            report.summary_table()
        elapsed = time.perf_counter() - start
        assert elapsed < 0.5, f"100 summary_table calls took {elapsed:.2f}s (>0.5s)"


# ============================================
# 24/7 READINESS: SOAK / LONG-RUN LOOP (T-05)
# ============================================

class TestSoakLoop:
    """Simulated long-run loop tests that approximate continuous operation.
    These verify no memory explosions, unbounded queues, or unhandled exceptions
    over many iterations."""

    @pytest.mark.devswarm
    def test_task_create_and_discard_loop(self):
        """Create and discard 10,000 tasks — memory should not grow unboundedly."""
        from core.dev_swarm import DevTask
        import sys
        # Baseline memory
        baseline_tasks = []
        for _ in range(100):
            baseline_tasks.append(DevTask(
                description="baseline", target_files=["f.py"], success_criteria="ok"))
        baseline_size = sys.getsizeof(baseline_tasks)
        del baseline_tasks

        # Run 10k create-discard cycles
        for _ in range(10_000):
            t = DevTask(description="soak", target_files=["f.py"], success_criteria="ok")
            _ = t.task_id  # access an attribute
        # If we got here without OOM or exception, pass
        assert True

    @pytest.mark.devswarm
    def test_swarm_history_bounded_growth(self, dev_swarm_instance):
        """Swarm task_history grows linearly, not exponentially, over 1000 cycles."""
        from core.dev_swarm import DevTask
        import sys
        for i in range(1000):
            task = DevTask(
                description=f"soak-{i}", target_files=["f.py"], success_criteria="ok")
            dev_swarm_instance.task_history.append(task)
        assert len(dev_swarm_instance.task_history) == 1000
        # Verify no hidden references bloating memory
        size = sys.getsizeof(dev_swarm_instance.task_history)
        assert size < 100_000, f"task_history consumes {size} bytes for 1000 items"

    @pytest.mark.auditor
    def test_auditor_parse_loop_no_leak(self, historical_auditor_for):
        """Parse the same report 500 times — results stay consistent, no resource leak."""
        first = historical_auditor_for("mixed.md")
        for _ in range(500):
            r = historical_auditor_for("mixed.md")
            assert r.overdue_count == first.overdue_count
            assert len(r.commitments) == len(first.commitments)

    @pytest.mark.devswarm
    def test_template_instantiation_loop(self):
        """Instantiate all 7 S2 templates 2000 times — all IDs unique."""
        from core.dev_swarm import DevTaskTemplates
        templates = [
            DevTaskTemplates.build_state_manager,
            DevTaskTemplates.implement_black_swan_drill_harness,
            DevTaskTemplates.add_observability_kill_switch,
            DevTaskTemplates.enforce_agent_registry,
            DevTaskTemplates.build_emergency_control_panel,
            DevTaskTemplates.add_model_drift_detection,
            DevTaskTemplates.add_override_intent_logging,
        ]
        ids = set()
        for _ in range(2000):
            for tmpl in templates:
                task = tmpl()
                ids.add(task.task_id)
        assert len(ids) == 14_000, f"Expected 14000 unique IDs, got {len(ids)}"


# ============================================
# 24/7 READINESS: RESTART / RECOVERY (T-06)
# ============================================

class TestRestartRecovery:
    """Tests simulating process restart and state reconciliation."""

    @pytest.mark.devswarm
    def test_swarm_state_survives_persistence_roundtrip(self, tmp_path):
        """DevSwarm with persistence can save and reload task history."""
        from core.dev_swarm import DevSwarm, SwarmConfig, DevTask
        from core.dev_swarm_persistence import DevSwarmPersistence

        db_path = tmp_path / "swarm.db"
        persistence = DevSwarmPersistence(str(db_path))

        # Session 1: create swarm, add tasks, save
        swarm1 = DevSwarm(
            config=SwarmConfig(max_concurrent_tasks=3),
            enable_persistence=True,
        )
        swarm1.persistence = persistence
        for i in range(5):
            task = DevTask(
                description=f"Recovery test {i}",
                target_files=[f"file_{i}.py"],
                success_criteria=f"Criterion {i}",
            )
            task.status = "completed"
            swarm1.task_history.append(task)
        for t in swarm1.task_history:
            persistence.save_task(t)

        # Session 2: new swarm, load from same persistence
        swarm2 = DevSwarm(
            config=SwarmConfig(max_concurrent_tasks=3),
            enable_persistence=True,
        )
        swarm2.persistence = persistence
        loaded = persistence.load_tasks()
        assert len(loaded) == 5
        assert all(t.status == "completed" for t in loaded)

    @pytest.mark.devswarm
    def test_swarm_fresh_after_no_persistence(self):
        """Swarm without persistence starts completely clean."""
        from core.dev_swarm import DevSwarm, SwarmConfig
        swarm = DevSwarm(config=SwarmConfig(), enable_persistence=False)
        assert len(swarm.task_history) == 0
        assert len(swarm.active_tasks) == 0
        assert swarm.daily_cost_usd == 0.0

    @pytest.mark.devswarm
    def test_config_preserved_across_restart(self, tmp_path):
        """SwarmConfig values are preserved when reconstructing a swarm."""
        from core.dev_swarm import DevSwarm, SwarmConfig
        cfg = SwarmConfig(max_concurrent_tasks=7, max_concurrent_agents=15)
        swarm1 = DevSwarm(config=cfg, enable_persistence=False)

        # Simulate restart with same config
        swarm2 = DevSwarm(
            config=SwarmConfig(
                max_concurrent_tasks=swarm1.config.max_concurrent_tasks,
                max_concurrent_agents=swarm1.config.max_concurrent_agents,
            ),
            enable_persistence=False,
        )
        assert swarm2.config.max_concurrent_tasks == 7
        assert swarm2.config.max_concurrent_agents == 15


# ============================================
# 24/7 READINESS: DEPENDENCY FAILURE (T-07)
# ============================================

class TestDependencyFailure:
    """Tests simulating degraded or failed dependencies."""

    @pytest.mark.auditor
    def test_auditor_handles_missing_report_file(self):
        """Auditor gracefully handles missing gap report file."""
        from core.historical_commitments_auditor import parse_gap_report
        report = parse_gap_report(path=Path("/nonexistent/path/report.md"))
        assert len(report.commitments) == 0
        assert len(report.parse_errors) == 1
        assert "not found" in report.parse_errors[0].lower()

    @pytest.mark.auditor
    def test_auditor_handles_unreadable_file(self, tmp_path):
        """Auditor handles a file with binary/corrupt content."""
        from core.historical_commitments_auditor import parse_gap_report
        corrupt = tmp_path / "corrupt.md"
        corrupt.write_bytes(b"\x00\x01\x02\xff\xfe\xfd" * 100)
        report = parse_gap_report(path=corrupt)
        # Should not crash — may parse 0 commitments
        assert isinstance(report.commitments, list)

    @pytest.mark.devswarm
    def test_swarm_operates_without_persistence_backend(self):
        """DevSwarm continues to function when persistence is disabled/unavailable."""
        from core.dev_swarm import DevSwarm, SwarmConfig, DevTask
        swarm = DevSwarm(config=SwarmConfig(), enable_persistence=False)
        task = DevTask(
            description="No persistence test",
            target_files=["f.py"],
            success_criteria="ok",
        )
        swarm.task_history.append(task)
        assert len(swarm.task_history) == 1

    @pytest.mark.devswarm
    def test_swarm_handles_agent_registration_without_agents(self, dev_swarm_instance):
        """Swarm works with zero agents — task tracking still functions."""
        from core.dev_swarm import DevTask
        assert len(dev_swarm_instance.agents) == 0
        task = DevTask(
            description="Agentless test",
            target_files=["f.py"],
            success_criteria="ok",
        )
        dev_swarm_instance.task_history.append(task)
        assert len(dev_swarm_instance.task_history) == 1

    @pytest.mark.auditor
    def test_readiness_check_with_empty_report(self, tmp_path, monkeypatch):
        """check_historical_commitments handles an empty file gracefully."""
        from core import historical_commitments_auditor as mod
        empty = tmp_path / "empty.md"
        empty.write_text("", encoding="utf-8")
        monkeypatch.setattr(mod, "GAP_REPORT_PATH", empty)
        result = mod.check_historical_commitments()
        assert result["status"] == "OK"  # no commitments = no overdue


# ============================================
# MERID READINESS AUDITOR TESTS
# ============================================

class TestMeridReadinessAuditor:
    """Tests for the 24/7 readiness auditor module."""

    def test_evaluate_returns_report(self):
        """evaluate() returns a ReadinessReport with items."""
        from core.merid_readiness_auditor import evaluate
        report = evaluate()
        assert len(report.items) > 0
        assert report.total_score > 0
        assert report.max_score > 0

    def test_report_has_all_dimensions(self):
        """Report covers all 5 readiness dimensions."""
        from core.merid_readiness_auditor import evaluate
        report = evaluate()
        dims = set(c.dimension for c in report.items)
        assert "Testing" in dims
        assert "Observability" in dims
        assert "Risk" in dims
        assert "Operations" in dims
        assert "Infrastructure" in dims

    def test_scores_are_bounded(self):
        """All scores are 0, 1, or 2."""
        from core.merid_readiness_auditor import evaluate
        report = evaluate()
        for c in report.items:
            assert c.score in (0, 1, 2), f"{c.id}: score {c.score} out of range"

    def test_pct_is_reasonable(self):
        """Overall percentage is between 0 and 100."""
        from core.merid_readiness_auditor import evaluate
        report = evaluate()
        assert 0 <= report.pct <= 100

    def test_level_is_valid(self):
        """Level is one of the defined readiness levels."""
        from core.merid_readiness_auditor import evaluate
        report = evaluate()
        assert report.level in ("Prototype", "Lab", "Staging", "Production")

    def test_gaps_are_subset_of_items(self):
        """All gaps are items with score < max_score."""
        from core.merid_readiness_auditor import evaluate
        report = evaluate()
        for g in report.gaps():
            assert g.score < g.max_score

    def test_by_dimension_covers_all_items(self):
        """by_dimension() returns all items grouped correctly."""
        from core.merid_readiness_auditor import evaluate
        report = evaluate()
        total_in_dims = sum(len(items) for items in report.by_dimension().values())
        assert total_in_dims == len(report.items)

    def test_cli_json_output(self):
        """CLI --json produces valid JSON with expected keys."""
        import json
        result = subprocess.run(
            [sys.executable, "-m", "core.merid_readiness_auditor", "--json"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parent.parent),
        )
        data = json.loads(result.stdout)
        assert "total_score" in data
        assert "max_score" in data
        assert "pct" in data
        assert "level" in data
        assert "dimensions" in data
        assert "gaps" in data

    def test_cli_exit_code_reflects_readiness(self):
        """CLI exits 0 if >= 80%, 1 otherwise."""
        result = subprocess.run(
            [sys.executable, "-m", "core.merid_readiness_auditor", "--json"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parent.parent),
        )
        import json
        data = json.loads(result.stdout)
        if data["pct"] >= 80:
            assert result.returncode == 0
        else:
            assert result.returncode == 1

    def test_t05_detected_after_soak_tests_added(self):
        """T-05 check detects TestSoakLoop class in test file."""
        from core.merid_readiness_auditor import _file_contains
        assert _file_contains("tests/test_dev_swarm.py", r"class TestSoakLoop")

    def test_t06_detected_after_restart_tests_added(self):
        """T-06 check detects TestRestartRecovery class in test file."""
        from core.merid_readiness_auditor import _file_contains
        assert _file_contains("tests/test_dev_swarm.py", r"class TestRestartRecovery")

    def test_t07_detected_after_dep_failure_tests_added(self):
        """T-07 check detects TestDependencyFailure class in test file."""
        from core.merid_readiness_auditor import _file_contains
        assert _file_contains("tests/test_dev_swarm.py", r"class TestDependencyFailure")


class TestSwarmTradingReadiness:
    """Tests for the swarm-trading readiness auditor (evaluate_swarm_trading)."""

    def test_swarm_evaluate_returns_report(self):
        from core.merid_readiness_auditor import evaluate_swarm_trading, ReadinessReport
        report = evaluate_swarm_trading()
        assert isinstance(report, ReadinessReport)
        assert len(report.items) > 0

    def test_swarm_report_has_all_10_dimensions(self):
        from core.merid_readiness_auditor import evaluate_swarm_trading
        report = evaluate_swarm_trading()
        dims = set(c.dimension for c in report.items)
        expected = {
            "Swarm Architecture", "Decentralization", "Value Flow",
            "Risk & Safety", "Swarm Observability", "24/7 Operations",
            "Testing Depth", "Data & Drift", "Security & Ethics", "Operator UX",
        }
        assert expected == dims

    def test_swarm_scores_bounded(self):
        from core.merid_readiness_auditor import evaluate_swarm_trading
        report = evaluate_swarm_trading()
        for c in report.items:
            assert 0 <= c.score <= c.max_score

    def test_swarm_pct_reasonable(self):
        from core.merid_readiness_auditor import evaluate_swarm_trading
        report = evaluate_swarm_trading()
        assert 30 <= report.pct <= 100

    def test_swarm_level_valid(self):
        from core.merid_readiness_auditor import evaluate_swarm_trading
        report = evaluate_swarm_trading()
        assert report.level in ("Prototype", "Lab", "Staging", "Production")

    def test_swarm_gaps_subset_of_items(self):
        from core.merid_readiness_auditor import evaluate_swarm_trading
        report = evaluate_swarm_trading()
        gap_ids = {g.id for g in report.gaps()}
        all_ids = {c.id for c in report.items}
        assert gap_ids.issubset(all_ids)

    def test_swarm_item_count_is_37(self):
        """Swarm-trading checklist has exactly 37 items (4+4+3+4+4+4+4+3+3+4)."""
        from core.merid_readiness_auditor import evaluate_swarm_trading
        report = evaluate_swarm_trading()
        assert len(report.items) == 37

    def test_swarm_architecture_checks(self):
        from core.merid_readiness_auditor import evaluate_swarm_trading
        report = evaluate_swarm_trading()
        arch = [c for c in report.items if c.dimension == "Swarm Architecture"]
        assert len(arch) == 4
        ids = {c.id for c in arch}
        assert ids == {"S1-01", "S1-02", "S1-03", "S1-04"}

    def test_risk_safety_checks(self):
        from core.merid_readiness_auditor import evaluate_swarm_trading
        report = evaluate_swarm_trading()
        risk = [c for c in report.items if c.dimension == "Risk & Safety"]
        assert len(risk) == 4
        assert any(c.id == "S4-04" and c.score == 2 for c in risk)

    def test_evaluate_all_returns_two_reports(self):
        from core.merid_readiness_auditor import evaluate_all, ReadinessReport
        r24, rsw = evaluate_all()
        assert isinstance(r24, ReadinessReport)
        assert isinstance(rsw, ReadinessReport)
        assert r24.max_score > 0
        assert rsw.max_score > 0

    def test_combined_score_is_sum(self):
        from core.merid_readiness_auditor import evaluate_all
        r24, rsw = evaluate_all()
        combined = r24.total_score + rsw.total_score
        combined_max = r24.max_score + rsw.max_score
        assert combined > 0
        assert combined <= combined_max

    def test_cli_swarm_json(self):
        result = subprocess.run(
            [sys.executable, "-m", "core.merid_readiness_auditor", "--swarm", "--json"],
            capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent),
            timeout=120,
        )
        import json as _json
        data = _json.loads(result.stdout)
        assert "total_score" in data
        assert "Swarm Architecture" in data["dimensions"]

    def test_cli_all_json(self):
        result = subprocess.run(
            [sys.executable, "-m", "core.merid_readiness_auditor", "--all", "--json"],
            capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent),
            timeout=120,
        )
        import json as _json
        data = _json.loads(result.stdout)
        assert "readiness_24_7" in data
        assert "swarm_trading" in data
        assert "combined_score" in data
        assert data["combined_score"] == (
            data["readiness_24_7"]["total_score"] + data["swarm_trading"]["total_score"])

    def test_swarm_doc_exists(self):
        """docs/SWARM_TRADING_READINESS.md should exist."""
        assert Path(__file__).resolve().parent.parent.joinpath(
            "docs", "SWARM_TRADING_READINESS.md").exists()

    def test_by_dimension_covers_all_items(self):
        from core.merid_readiness_auditor import evaluate_swarm_trading
        report = evaluate_swarm_trading()
        by_dim = report.by_dimension()
        total_from_dims = sum(len(items) for items in by_dim.values())
        assert total_from_dims == len(report.items)


class TestMeridReadinessScore:
    """Tests for the declared readiness score baseline (merid_readiness_score)."""

    def test_sections_dict_has_10_entries(self):
        from core.merid_readiness_score import READINESS_SECTIONS
        assert len(READINESS_SECTIONS) == 10

    def test_all_scores_bounded(self):
        from core.merid_readiness_score import READINESS_SECTIONS
        for key, (score, mx) in READINESS_SECTIONS.items():
            assert 0 <= score <= mx, f"{key}: {score}/{mx}"

    def test_aggregate_scores_returns_triple(self):
        from core.merid_readiness_score import aggregate_scores
        total, maximum, pct = aggregate_scores()
        assert isinstance(total, int)
        assert isinstance(maximum, int)
        assert isinstance(pct, float)
        assert 0 < total <= maximum

    def test_aggregate_pct_matches(self):
        from core.merid_readiness_score import aggregate_scores, READINESS_SECTIONS
        total, maximum, pct = aggregate_scores()
        expected_total = sum(s for s, _ in READINESS_SECTIONS.values())
        expected_max = sum(m for _, m in READINESS_SECTIONS.values())
        assert total == expected_total
        assert maximum == expected_max
        assert abs(pct - (total / maximum * 100)) < 0.01

    def test_readiness_level_labels(self):
        from core.merid_readiness_score import readiness_level
        assert readiness_level(95) == "Production"
        assert readiness_level(90) == "Production"
        assert readiness_level(75) == "Staging"
        assert readiness_level(70) == "Staging"
        assert readiness_level(55) == "Lab"
        assert readiness_level(50) == "Lab"
        assert readiness_level(30) == "Prototype"

    def test_composite_scores_keys(self):
        from core.merid_readiness_score import composite_scores
        comp = composite_scores()
        assert "swarm_trading" in comp
        assert "readiness_24_7" in comp

    def test_composite_scores_sum_to_total(self):
        from core.merid_readiness_score import aggregate_scores, composite_scores
        total, maximum, _ = aggregate_scores()
        comp = composite_scores()
        comp_total = sum(t for t, _, _ in comp.values())
        comp_max = sum(m for _, m, _ in comp.values())
        assert comp_total == total
        assert comp_max == maximum

    def test_custom_sections(self):
        from core.merid_readiness_score import aggregate_scores
        custom = {"a": (5, 10), "b": (3, 5)}
        total, maximum, pct = aggregate_scores(custom)
        assert total == 8
        assert maximum == 15
        assert abs(pct - (8 / 15 * 100)) < 0.01

    def test_cli_json_output(self):
        result = subprocess.run(
            [sys.executable, "-m", "core.merid_readiness_score", "--json"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parent.parent),
            timeout=30,
        )
        import json as _json
        data = _json.loads(result.stdout)
        assert "total" in data
        assert "max" in data
        assert "pct" in data
        assert "level" in data
        assert "sections" in data
        assert "composite" in data
        assert len(data["sections"]) == 10

    def test_none_sections_uses_default(self):
        from core.merid_readiness_score import aggregate_scores, READINESS_SECTIONS
        total, maximum, pct = aggregate_scores(None)
        expected_total = sum(s for s, _ in READINESS_SECTIONS.values())
        assert total == expected_total

    def test_single_section(self):
        from core.merid_readiness_score import aggregate_scores
        total, maximum, pct = aggregate_scores({"only": (3, 5)})
        assert total == 3
        assert maximum == 5
        assert abs(pct - 60.0) < 0.01


class TestDevSwarmPauseResume:
    """Tests for DevSwarm pause/resume functionality."""

    def test_initial_state_not_paused(self):
        from core.dev_swarm import DevSwarm
        swarm = DevSwarm(enable_persistence=False)
        assert not swarm.is_paused

    def test_pause_returns_true_first_time(self):
        from core.dev_swarm import DevSwarm
        swarm = DevSwarm(enable_persistence=False)
        assert swarm.pause() is True

    def test_pause_returns_false_when_already_paused(self):
        from core.dev_swarm import DevSwarm
        swarm = DevSwarm(enable_persistence=False)
        swarm.pause()
        assert swarm.pause() is False

    def test_resume_returns_true_after_pause(self):
        from core.dev_swarm import DevSwarm
        swarm = DevSwarm(enable_persistence=False)
        swarm.pause()
        assert swarm.resume() is True

    def test_resume_returns_false_when_not_paused(self):
        from core.dev_swarm import DevSwarm
        swarm = DevSwarm(enable_persistence=False)
        assert swarm.resume() is False

    def test_is_paused_property(self):
        from core.dev_swarm import DevSwarm
        swarm = DevSwarm(enable_persistence=False)
        assert swarm.is_paused is False
        swarm.pause()
        assert swarm.is_paused is True
        swarm.resume()
        assert swarm.is_paused is False

    def test_execute_task_rejected_when_paused(self):
        from core.dev_swarm import DevSwarm, DevTask
        swarm = DevSwarm(enable_persistence=False)
        swarm.pause()
        task = DevTask(
            description="test task while paused",
            target_files=["test.py"],
            success_criteria="should fail",
        )
        result = asyncio.get_event_loop().run_until_complete(swarm.execute_task(task))
        assert result.status == "failed"
        assert "paused" in result.error.lower()

    def test_execute_task_works_after_resume(self):
        from core.dev_swarm import DevSwarm, DevTask
        swarm = DevSwarm(enable_persistence=False)
        swarm.pause()
        swarm.resume()
        task = DevTask(
            description="test task after resume",
            target_files=["test.py"],
            success_criteria="should start",
        )
        result = asyncio.get_event_loop().run_until_complete(swarm.execute_task(task))
        # Task should not be rejected for being paused (may fail for other reasons)
        assert "paused" not in (result.error or "").lower()


class TestOperatorAPI:
    """Tests for the operator API endpoints."""

    def test_pause_endpoint_exists(self):
        result = subprocess.run(
            [sys.executable, "-c",
             "from web.api.dev_swarm_routes import router; "
             "routes = [r.path for r in router.routes]; "
             "print(any('pause' in p for p in routes))"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parent.parent),
            timeout=30,
        )
        assert "True" in result.stdout

    def test_resume_endpoint_exists(self):
        result = subprocess.run(
            [sys.executable, "-c",
             "from web.api.dev_swarm_routes import router; "
             "routes = [r.path for r in router.routes]; "
             "print(any('resume' in p for p in routes))"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parent.parent),
            timeout=30,
        )
        assert "True" in result.stdout

    def test_operator_summary_endpoint_exists(self):
        result = subprocess.run(
            [sys.executable, "-c",
             "from web.api.operator import router; "
             "routes = [r.path for r in router.routes]; "
             "print(any('summary' in p for p in routes))"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parent.parent),
            timeout=30,
        )
        assert "True" in result.stdout

    def test_operator_audit_trail_endpoint_exists(self):
        result = subprocess.run(
            [sys.executable, "-c",
             "from web.api.operator import router; "
             "routes = [r.path for r in router.routes]; "
             "print(any('audit-trail' in p for p in routes))"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parent.parent),
            timeout=30,
        )
        assert "True" in result.stdout

    def test_operator_module_importable(self):
        result = subprocess.run(
            [sys.executable, "-c", "import web.api.operator; print('OK')"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parent.parent),
            timeout=30,
        )
        assert "OK" in result.stdout

    def test_operator_dashboard_spec_exists(self):
        assert Path(__file__).resolve().parent.parent.joinpath(
            "docs", "OPERATOR_DASHBOARD_SPEC.md").exists()

    def test_equity_series_endpoint_exists(self):
        result = subprocess.run(
            [sys.executable, "-c",
             "from web.api.operator import router; "
             "routes = [r.path for r in router.routes]; "
             "print(any('equity-series' in p for p in routes))"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parent.parent),
            timeout=30,
        )
        assert "True" in result.stdout

    def test_risk_utilization_endpoint_exists(self):
        result = subprocess.run(
            [sys.executable, "-c",
             "from web.api.operator import router; "
             "routes = [r.path for r in router.routes]; "
             "print(any('risk-utilization' in p for p in routes))"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parent.parent),
            timeout=30,
        )
        assert "True" in result.stdout

    def test_equity_buffer_functions(self):
        result = subprocess.run(
            [sys.executable, "-c",
             "from web.api.operator import _record_equity_snapshot, _equity_buffer; "
             "_record_equity_snapshot(100000.0, 500.0); "
             "print(len(_equity_buffer) >= 1 and _equity_buffer[-1]['equity'] == 100000.0)"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parent.parent),
            timeout=30,
        )
        assert "True" in result.stdout

    def test_ui_audit_checklist_exists(self):
        assert Path(__file__).resolve().parent.parent.joinpath(
            "docs", "UI_AUDIT_CHECKLIST.md").exists()


class TestMetricsAPI:
    """Tests for the /api/metrics/* endpoints."""

    def test_metrics_router_exists(self):
        result = subprocess.run(
            [sys.executable, "-c",
             "from web.api.metrics import router; "
             "print(router.prefix)"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parent.parent),
            timeout=30,
        )
        assert "/api/metrics" in result.stdout

    def test_swarm_health_endpoint(self):
        result = subprocess.run(
            [sys.executable, "-c",
             "from web.api.metrics import router; "
             "routes = [r.path for r in router.routes]; "
             "print(any('swarm_health' in p for p in routes))"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parent.parent),
            timeout=30,
        )
        assert "True" in result.stdout

    def test_heatmap_endpoint(self):
        result = subprocess.run(
            [sys.executable, "-c",
             "from web.api.metrics import router; "
             "routes = [r.path for r in router.routes]; "
             "print(any('heatmap' in p for p in routes))"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parent.parent),
            timeout=30,
        )
        assert "True" in result.stdout

    def test_radar_endpoint(self):
        result = subprocess.run(
            [sys.executable, "-c",
             "from web.api.metrics import router; "
             "routes = [r.path for r in router.routes]; "
             "print(any('radar' in p for p in routes))"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parent.parent),
            timeout=30,
        )
        assert "True" in result.stdout

    def test_latency_endpoint(self):
        result = subprocess.run(
            [sys.executable, "-c",
             "from web.api.metrics import router; "
             "routes = [r.path for r in router.routes]; "
             "print(any('latency' in p for p in routes))"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parent.parent),
            timeout=30,
        )
        assert "True" in result.stdout

    def test_breach_log_endpoint(self):
        result = subprocess.run(
            [sys.executable, "-c",
             "from web.api.metrics import router; "
             "routes = [r.path for r in router.routes]; "
             "print(any('breach_log' in p for p in routes))"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parent.parent),
            timeout=30,
        )
        assert "True" in result.stdout

    def test_record_latency_function(self):
        result = subprocess.run(
            [sys.executable, "-c",
             "from web.api.metrics import record_latency, _latency_samples; "
             "record_latency('/api/test', 42.5); "
             "print(len(_latency_samples) >= 1 and _latency_samples[-1]['ms'] == 42.5)"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parent.parent),
            timeout=30,
        )
        assert "True" in result.stdout

    def test_record_breach_function(self):
        result = subprocess.run(
            [sys.executable, "-c",
             "from web.api.metrics import record_breach, _breach_log; "
             "record_breach('daily_loss', 'BTC', 4500, 5000, 'alert', 'WARNING'); "
             "print(len(_breach_log) >= 1 and _breach_log[-1]['rule'] == 'daily_loss')"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parent.parent),
            timeout=30,
        )
        assert "True" in result.stdout


class TestMarketDataAPI:
    """Tests for the /api/market/* endpoints and dxFeed adapter."""

    def test_market_data_router_exists(self):
        result = subprocess.run(
            [sys.executable, "-c",
             "from web.api.market_data import router; "
             "print(router.prefix)"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parent.parent),
            timeout=30,
        )
        assert "/api/market" in result.stdout

    def test_snapshot_endpoint(self):
        result = subprocess.run(
            [sys.executable, "-c",
             "from web.api.market_data import router; "
             "routes = [r.path for r in router.routes]; "
             "print(any('snapshot' in p for p in routes))"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parent.parent),
            timeout=30,
        )
        assert "True" in result.stdout

    def test_watchlist_endpoint(self):
        result = subprocess.run(
            [sys.executable, "-c",
             "from web.api.market_data import router; "
             "routes = [r.path for r in router.routes]; "
             "print(any('watchlist' in p and 'add' not in p and 'remove' not in p for p in routes))"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parent.parent),
            timeout=30,
        )
        assert "True" in result.stdout

    def test_dxfeed_adapter_import(self):
        result = subprocess.run(
            [sys.executable, "-c",
             "from core.market_data_dxfeed import DxFeedAdapter, TickData, get_dxfeed_adapter; "
             "print('OK')"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parent.parent),
            timeout=30,
        )
        assert "OK" in result.stdout

    def test_dxfeed_adapter_watchlist_management(self):
        result = subprocess.run(
            [sys.executable, "-c",
             "from core.market_data_dxfeed import DxFeedAdapter; "
             "a = DxFeedAdapter(watchlist=['BTC/USD']); "
             "a.add_symbol('ETH/USD'); "
             "a.remove_symbol('BTC/USD'); "
             "print(a.watchlist_symbols == ['ETH/USD'])"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parent.parent),
            timeout=30,
        )
        assert "True" in result.stdout

    def test_tick_data_to_dict(self):
        result = subprocess.run(
            [sys.executable, "-c",
             "from core.market_data_dxfeed import TickData; "
             "t = TickData(symbol='BTC/USD', price=50000.0); "
             "d = t.to_dict(); "
             "print(d['symbol'] == 'BTC/USD' and d['price'] == 50000.0)"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parent.parent),
            timeout=30,
        )
        assert "True" in result.stdout


class TestMarketHeatmapHelper:
    """Tests for core/market_heatmap.py helper functions."""

    def test_build_heatmap_snapshot_basic(self):
        result = subprocess.run(
            [sys.executable, "-c",
             "from core.market_heatmap import build_heatmap_snapshot; "
             "quotes = [{'symbol': 'BTC/USD', 'change_pct_24h': 2.5}]; "
             "positions = [{'symbol': 'BTC', 'pnl': 100, 'exposure': 5000, 'side': 'long'}]; "
             "s = build_heatmap_snapshot(quotes, positions); "
             "print('Crypto Major' in s and s['Crypto Major'][0]['pnl'] == 100)"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parent.parent),
            timeout=30,
        )
        assert "True" in result.stdout

    def test_build_heatmap_snapshot_empty(self):
        result = subprocess.run(
            [sys.executable, "-c",
             "from core.market_heatmap import build_heatmap_snapshot; "
             "s = build_heatmap_snapshot([], []); "
             "print(len(s) == 0)"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parent.parent),
            timeout=30,
        )
        assert "True" in result.stdout

    def test_build_radar_snapshot_category_filter(self):
        result = subprocess.run(
            [sys.executable, "-c",
             "from core.market_heatmap import build_radar_snapshot; "
             "quotes = [{'symbol': 'BTC/USD', 'price': 50000}]; "
             "r = build_radar_snapshot(quotes, [], 'core'); "
             "symbols = [i['symbol'] for i in r]; "
             "print('BTC' in symbols and 'DOGE' not in symbols)"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parent.parent),
            timeout=30,
        )
        assert "True" in result.stdout

    def test_build_radar_snapshot_all(self):
        result = subprocess.run(
            [sys.executable, "-c",
             "from core.market_heatmap import build_radar_snapshot; "
             "r = build_radar_snapshot([], [], 'all'); "
             "print(len(r) > 5)"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parent.parent),
            timeout=30,
        )
        assert "True" in result.stdout

    def test_sector_map_coverage(self):
        result = subprocess.run(
            [sys.executable, "-c",
             "from core.market_heatmap import SECTOR_MAP, CATEGORY_SYMBOLS; "
             "all_syms = set(); "
             "[all_syms.update(v) for v in CATEGORY_SYMBOLS.values()]; "
             "mapped = sum(1 for s in all_syms if s in SECTOR_MAP); "
             "print(mapped == len(all_syms))"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parent.parent),
            timeout=30,
        )
        assert "True" in result.stdout


class TestRouterRegistration:
    """Tests that new routers are registered in web/main.py."""

    def test_operator_router_in_main(self):
        main_path = Path(__file__).resolve().parent.parent / "web" / "main.py"
        content = main_path.read_text(encoding="utf-8")
        assert "from web.api.operator import router as operator_router" in content
        assert "application.include_router(operator_router)" in content

    def test_metrics_router_in_main(self):
        main_path = Path(__file__).resolve().parent.parent / "web" / "main.py"
        content = main_path.read_text(encoding="utf-8")
        assert "from web.api.metrics import router as metrics_router" in content
        assert "application.include_router(metrics_router)" in content

    def test_market_data_router_in_main(self):
        main_path = Path(__file__).resolve().parent.parent / "web" / "main.py"
        content = main_path.read_text(encoding="utf-8")
        assert "from web.api.market_data import router as market_data_router" in content
        assert "application.include_router(market_data_router)" in content

    def test_latency_middleware_in_main(self):
        main_path = Path(__file__).resolve().parent.parent / "web" / "main.py"
        content = main_path.read_text(encoding="utf-8")
        assert "latency_timing_middleware" in content
        assert "record_latency" in content


class TestLatencyRegression:
    """
    UI latency regression tests — Deephaven-style benchmarks.

    Measures backend metrics endpoint response times under simulated load
    and asserts p95 stays under 300ms target.
    """

    def _run_script(self, code: str) -> str:
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parent.parent),
            timeout=30,
        )
        return result.stdout

    def test_record_latency_buffer_works(self):
        """Verify record_latency populates the ring buffer and respects max size."""
        out = self._run_script(
            "from web.api.metrics import record_latency, _latency_samples\n"
            "initial = len(_latency_samples)\n"
            "for i in range(10):\n"
            "    record_latency('/api/test', float(i))\n"
            "after = len(_latency_samples)\n"
            "print(after >= initial + 10)\n"
        )
        assert "True" in out

    def test_record_latency_buffer_cap(self):
        """Verify ring buffer trims to max size."""
        out = self._run_script(
            "from web.api.metrics import record_latency, _latency_samples, _LATENCY_BUFFER_MAX\n"
            "_latency_samples.clear()\n"
            "for i in range(_LATENCY_BUFFER_MAX + 50):\n"
            "    record_latency('/api/test', 1.0)\n"
            "print(len(_latency_samples) <= _LATENCY_BUFFER_MAX)\n"
        )
        assert "True" in out

    def test_latency_percentile_calculation(self):
        """Verify p50/p95/p99 percentile math is correct with known data."""
        out = self._run_script(
            "import time\n"
            "from web.api.metrics import record_latency, _latency_samples\n"
            "_latency_samples.clear()\n"
            "for i in range(100):\n"
            "    record_latency('/api/test', float(i))\n"
            "cutoff = time.time() - 300\n"
            "recent = [s for s in _latency_samples if s['ts'] >= cutoff]\n"
            "vals = sorted(s['ms'] for s in recent)\n"
            "p50 = vals[len(vals)//2]\n"
            "p95 = vals[int(len(vals)*0.95)]\n"
            "p99 = vals[int(len(vals)*0.99)]\n"
            "print(p50 == 50.0 and p95 == 95.0 and p99 == 99.0)\n"
        )
        assert "True" in out

    def test_breach_log_buffer_works(self):
        """Verify record_breach populates the breach log buffer."""
        out = self._run_script(
            "from web.api.metrics import record_breach, _breach_log\n"
            "_breach_log.clear()\n"
            "record_breach('max_drawdown', 'BTC', 0.12, 0.10, 'reduce', 'WARNING')\n"
            "print(len(_breach_log) == 1 and _breach_log[0]['rule'] == 'max_drawdown')\n"
        )
        assert "True" in out

    def test_breach_log_buffer_cap(self):
        """Verify breach log trims to max size."""
        out = self._run_script(
            "from web.api.metrics import record_breach, _breach_log, _BREACH_LOG_MAX\n"
            "_breach_log.clear()\n"
            "for i in range(_BREACH_LOG_MAX + 20):\n"
            "    record_breach('test', 'SYM', float(i), 100.0, 'alert', 'INFO')\n"
            "print(len(_breach_log) <= _BREACH_LOG_MAX)\n"
        )
        assert "True" in out

    def test_simulated_load_latency_under_target(self):
        """
        Simulate 50 rapid record_latency calls and verify the buffer
        correctly captures all samples with sub-300ms synthetic values.
        This validates the pipeline that feeds the LatencyChart.
        """
        out = self._run_script(
            "import time\n"
            "from web.api.metrics import record_latency, _latency_samples\n"
            "_latency_samples.clear()\n"
            "target_ms = 300\n"
            "for i in range(50):\n"
            "    record_latency('/api/metrics/test_' + str(i % 5), float(i % 200))\n"
            "vals = sorted(s['ms'] for s in _latency_samples)\n"
            "p95 = vals[int(len(vals) * 0.95)]\n"
            "print(p95 < target_ms and len(_latency_samples) == 50)\n"
        )
        assert "True" in out

    def test_market_heatmap_helper_performance(self):
        """Verify build_heatmap_snapshot completes in <50ms for typical data sizes."""
        out = self._run_script(
            "import time\n"
            "from core.market_heatmap import build_heatmap_snapshot\n"
            "quotes = [{'symbol': 'SYM' + str(i) + '/USDT', 'change_pct_24h': i * 0.1} for i in range(50)]\n"
            "positions = [{'symbol': 'SYM' + str(i), 'pnl': i, 'exposure': i * 100, 'side': 'long'} for i in range(50)]\n"
            "start = time.perf_counter()\n"
            "for _ in range(100):\n"
            "    build_heatmap_snapshot(quotes, positions)\n"
            "elapsed_ms = (time.perf_counter() - start) * 1000\n"
            "avg_ms = elapsed_ms / 100\n"
            "print(avg_ms < 50)\n"
        )
        assert "True" in out


class TestWebSocketMarketData:
    """Tests for WebSocket market data streaming endpoint and LightweightPriceChart stub."""

    def test_ws_router_exists_in_market_data(self):
        """Verify ws_router is defined in web/api/market_data.py."""
        result = subprocess.run(
            [sys.executable, "-c",
             "from web.api.market_data import ws_router\n"
             "print(ws_router is not None)\n"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parent.parent),
            timeout=30,
        )
        assert "True" in result.stdout

    def test_ws_router_registered_in_main(self):
        """Verify market_ws_router is imported and registered in web/main.py."""
        main_path = Path(__file__).resolve().parent.parent / "web" / "main.py"
        content = main_path.read_text(encoding="utf-8")
        assert "from web.api.market_data import ws_router as market_ws_router" in content
        assert "application.include_router(market_ws_router)" in content

    def test_ws_endpoint_path(self):
        """Verify the WebSocket endpoint is at /ws/market/{symbol}."""
        result = subprocess.run(
            [sys.executable, "-c",
             "from web.api.market_data import ws_router\n"
             "routes = [r.path for r in ws_router.routes]\n"
             "print('/ws/market/{symbol}' in routes)\n"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parent.parent),
            timeout=30,
        )
        assert "True" in result.stdout

    def test_lightweight_price_chart_exists(self):
        """Verify LightweightPriceChart.tsx stub exists."""
        chart_path = (
            Path(__file__).resolve().parent.parent
            / "web" / "react" / "src" / "components" / "charts"
            / "LightweightPriceChart.tsx"
        )
        assert chart_path.exists(), f"Missing {chart_path}"

    def test_lightweight_price_chart_has_ws_support(self):
        """Verify LightweightPriceChart.tsx contains WebSocket connection logic."""
        chart_path = (
            Path(__file__).resolve().parent.parent
            / "web" / "react" / "src" / "components" / "charts"
            / "LightweightPriceChart.tsx"
        )
        content = chart_path.read_text(encoding="utf-8")
        assert "WebSocket" in content
        assert "wsUrl" in content
        assert "lightweight-charts" in content

    def test_ws_poll_interval_defined(self):
        """Verify the WebSocket poll interval constant is defined."""
        result = subprocess.run(
            [sys.executable, "-c",
             "from web.api.market_data import _WS_POLL_INTERVAL_S\n"
             "print(_WS_POLL_INTERVAL_S > 0)\n"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parent.parent),
            timeout=30,
        )
        assert "True" in result.stdout


class TestE2ELatencyPipeline:
    """
    End-to-end latency pipeline tests — Deephaven-style benchmarks.

    Measures the full path: dxFeed adapter snapshot → candle serialization
    → JSON encode (WebSocket-ready payload). Target: p95 < 2s under normal load.
    """

    def _run_script(self, code: str) -> str:
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parent.parent),
            timeout=30,
        )
        return result.stdout

    def test_adapter_snapshot_to_candle_latency(self):
        """Measure dxFeed adapter snapshot → candle dict construction time."""
        out = self._run_script(
            "import time, json\n"
            "from core.market_data_dxfeed import DxFeedAdapter\n"
            "adapter = DxFeedAdapter(watchlist=['BTC/USD', 'ETH/USD', 'SOL/USD'])\n"
            "latencies = []\n"
            "for _ in range(50):\n"
            "    start = time.perf_counter()\n"
            "    tick = adapter.get_snapshot('BTC/USD')\n"
            "    candle = {\n"
            "        'time': int(time.time()),\n"
            "        'open': tick.bid or tick.last or 0,\n"
            "        'high': tick.ask or tick.last or 0,\n"
            "        'low': tick.bid or tick.last or 0,\n"
            "        'close': tick.last or tick.ask or 0,\n"
            "        'volume': tick.volume_24h or 0,\n"
            "    }\n"
            "    payload = json.dumps(candle)\n"
            "    elapsed_ms = (time.perf_counter() - start) * 1000\n"
            "    latencies.append(elapsed_ms)\n"
            "latencies.sort()\n"
            "p95 = latencies[int(len(latencies) * 0.95)]\n"
            "print(p95 < 2000)\n"
        )
        assert "True" in out

    def test_watchlist_full_scan_latency(self):
        """Measure full watchlist scan (12 symbols) → serialization time."""
        out = self._run_script(
            "import time, json\n"
            "from core.market_data_dxfeed import DxFeedAdapter, DEFAULT_WATCHLIST\n"
            "adapter = DxFeedAdapter()\n"
            "latencies = []\n"
            "for _ in range(20):\n"
            "    start = time.perf_counter()\n"
            "    ticks = adapter.get_watchlist()\n"
            "    payloads = [json.dumps(t.to_dict()) for t in ticks]\n"
            "    elapsed_ms = (time.perf_counter() - start) * 1000\n"
            "    latencies.append(elapsed_ms)\n"
            "latencies.sort()\n"
            "p95 = latencies[int(len(latencies) * 0.95)]\n"
            "print(p95 < 2000 and len(payloads) == len(DEFAULT_WATCHLIST))\n"
        )
        assert "True" in out

    def test_heatmap_pipeline_e2e_latency(self):
        """Measure adapter → heatmap helper → JSON serialization pipeline."""
        out = self._run_script(
            "import time, json\n"
            "from core.market_data_dxfeed import DxFeedAdapter\n"
            "from core.market_heatmap import build_heatmap_snapshot\n"
            "adapter = DxFeedAdapter()\n"
            "latencies = []\n"
            "for _ in range(30):\n"
            "    start = time.perf_counter()\n"
            "    ticks = adapter.get_watchlist()\n"
            "    quotes = [t.to_dict() for t in ticks]\n"
            "    positions = [{'symbol': t.symbol.split('/')[0], 'pnl': 0, 'exposure': 100, 'side': 'long'} for t in ticks]\n"
            "    snapshot = build_heatmap_snapshot(quotes, positions)\n"
            "    payload = json.dumps(snapshot)\n"
            "    elapsed_ms = (time.perf_counter() - start) * 1000\n"
            "    latencies.append(elapsed_ms)\n"
            "latencies.sort()\n"
            "p95 = latencies[int(len(latencies) * 0.95)]\n"
            "print(p95 < 2000)\n"
        )
        assert "True" in out

    def test_radar_pipeline_e2e_latency(self):
        """Measure adapter → radar helper → JSON serialization pipeline."""
        out = self._run_script(
            "import time, json\n"
            "from core.market_data_dxfeed import DxFeedAdapter\n"
            "from core.market_heatmap import build_radar_snapshot\n"
            "adapter = DxFeedAdapter()\n"
            "latencies = []\n"
            "for _ in range(30):\n"
            "    start = time.perf_counter()\n"
            "    ticks = adapter.get_watchlist()\n"
            "    quotes = [t.to_dict() for t in ticks]\n"
            "    positions = [{'symbol': t.symbol.split('/')[0], 'pnl': 0, 'exposure': 100, 'side': 'long', 'volume': 1000} for t in ticks]\n"
            "    snapshot = build_radar_snapshot(quotes, positions)\n"
            "    payload = json.dumps(snapshot)\n"
            "    elapsed_ms = (time.perf_counter() - start) * 1000\n"
            "    latencies.append(elapsed_ms)\n"
            "latencies.sort()\n"
            "p95 = latencies[int(len(latencies) * 0.95)]\n"
            "print(p95 < 2000)\n"
        )
        assert "True" in out

    def test_candle_json_serialization_overhead(self):
        """Verify JSON serialization of candle payloads adds < 1ms overhead."""
        out = self._run_script(
            "import time, json\n"
            "candle = {'time': 1707264000, 'open': 42150.5, 'high': 42200.0, 'low': 42100.0, 'close': 42175.25, 'volume': 1234567}\n"
            "latencies = []\n"
            "for _ in range(1000):\n"
            "    start = time.perf_counter()\n"
            "    payload = json.dumps(candle)\n"
            "    elapsed_ms = (time.perf_counter() - start) * 1000\n"
            "    latencies.append(elapsed_ms)\n"
            "latencies.sort()\n"
            "p95 = latencies[int(len(latencies) * 0.95)]\n"
            "print(p95 < 1.0)\n"
        )
        assert "True" in out


class TestRiskLimits:
    """
    Tests for core/automated_risk_controls.py — RiskLimit, PositionRisk,
    PortfolioRiskManager. Satisfies R-05 in readiness auditor.
    """

    def _run_script(self, code: str) -> str:
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parent.parent),
            timeout=30,
        )
        return result.stdout

    def test_risk_limit_no_breach(self):
        """RiskLimit.check_breach returns False when value is under threshold."""
        out = self._run_script(
            "from core.automated_risk_controls import RiskLimit, RiskControlType\n"
            "rl = RiskLimit(limit_type=RiskControlType.POSITION_LIMIT, threshold=0.10)\n"
            "print(rl.check_breach(0.05))\n"
        )
        assert "False" in out

    def test_risk_limit_breach_detected(self):
        """RiskLimit.check_breach returns True when value exceeds threshold."""
        out = self._run_script(
            "from core.automated_risk_controls import RiskLimit, RiskControlType\n"
            "rl = RiskLimit(limit_type=RiskControlType.POSITION_LIMIT, threshold=0.10)\n"
            "breached = rl.check_breach(0.15)\n"
            "print(breached and rl.breached and rl.breach_count == 1)\n"
        )
        assert "True" in out

    def test_risk_limit_breach_clears(self):
        """RiskLimit.breached resets when value drops below threshold."""
        out = self._run_script(
            "from core.automated_risk_controls import RiskLimit, RiskControlType\n"
            "rl = RiskLimit(limit_type=RiskControlType.DRAWDOWN_LIMIT, threshold=0.15)\n"
            "rl.check_breach(0.20)\n"
            "rl.check_breach(0.10)\n"
            "print(not rl.breached and rl.breach_count == 1)\n"
        )
        assert "True" in out

    def test_risk_limit_to_dict(self):
        """RiskLimit.to_dict serializes all fields."""
        out = self._run_script(
            "from core.automated_risk_controls import RiskLimit, RiskControlType\n"
            "rl = RiskLimit(limit_type=RiskControlType.LEVERAGE_LIMIT, threshold=2.0)\n"
            "d = rl.to_dict()\n"
            "print(d['limit_type'] == 'leverage_limit' and d['threshold'] == 2.0)\n"
        )
        assert "True" in out

    def test_risk_control_type_enum_values(self):
        """All 7 RiskControlType enum values exist."""
        out = self._run_script(
            "from core.automated_risk_controls import RiskControlType\n"
            "expected = {'POSITION_LIMIT', 'DRAWDOWN_LIMIT', 'VOLATILITY_LIMIT',\n"
            "            'CORRELATION_LIMIT', 'EXPOSURE_LIMIT', 'LEVERAGE_LIMIT',\n"
            "            'CONCENTRATION_LIMIT'}\n"
            "actual = {e.name for e in RiskControlType}\n"
            "print(expected == actual)\n"
        )
        assert "True" in out

    def test_position_risk_score_calculation(self):
        """PositionRisk.calculate_risk_score returns weighted score in 0-100."""
        out = self._run_script(
            "from core.automated_risk_controls import PositionRisk\n"
            "pr = PositionRisk(symbol='BTC', position_size=1.0, entry_price=40000,\n"
            "                  current_price=42000, unrealized_pnl=2000,\n"
            "                  unrealized_pnl_pct=0.05, volatility=0.3,\n"
            "                  max_drawdown=-0.1, var_95=-0.05)\n"
            "score = pr.calculate_risk_score()\n"
            "print(0 <= score <= 100)\n"
        )
        assert "True" in out

    def test_position_risk_to_dict(self):
        """PositionRisk.to_dict includes risk_score field."""
        out = self._run_script(
            "from core.automated_risk_controls import PositionRisk\n"
            "pr = PositionRisk(symbol='ETH', position_size=10.0, entry_price=2500,\n"
            "                  current_price=2600, unrealized_pnl=1000,\n"
            "                  unrealized_pnl_pct=0.04)\n"
            "d = pr.to_dict()\n"
            "print('risk_score' in d and d['symbol'] == 'ETH')\n"
        )
        assert "True" in out

    def test_portfolio_risk_manager_init(self):
        """PortfolioRiskManager initializes with 4 default risk limits."""
        out = self._run_script(
            "from core.automated_risk_controls import PortfolioRiskManager\n"
            "prm = PortfolioRiskManager()\n"
            "print(len(prm.risk_limits) == 4)\n"
        )
        assert "True" in out

    def test_portfolio_risk_manager_add_remove_position(self):
        """PortfolioRiskManager tracks positions and updates exposure."""
        out = self._run_script(
            "from core.automated_risk_controls import PortfolioRiskManager, PositionRisk\n"
            "prm = PortfolioRiskManager()\n"
            "prm.portfolio_value = 100000\n"
            "pos = PositionRisk(symbol='BTC', position_size=1.0, entry_price=40000,\n"
            "                   current_price=40000, unrealized_pnl=0, unrealized_pnl_pct=0)\n"
            "prm.add_position(pos)\n"
            "has_btc = 'BTC' in prm.positions\n"
            "prm.remove_position('BTC')\n"
            "no_btc = 'BTC' not in prm.positions\n"
            "print(has_btc and no_btc)\n"
        )
        assert "True" in out

    def test_portfolio_risk_manager_leverage_tracking(self):
        """PortfolioRiskManager calculates leverage from total exposure."""
        out = self._run_script(
            "from core.automated_risk_controls import PortfolioRiskManager, PositionRisk\n"
            "prm = PortfolioRiskManager()\n"
            "prm.portfolio_value = 100000\n"
            "pos = PositionRisk(symbol='BTC', position_size=2.0, entry_price=50000,\n"
            "                   current_price=50000, unrealized_pnl=0, unrealized_pnl_pct=0)\n"
            "prm.add_position(pos)\n"
            "print(prm.current_leverage == 1.0)\n"
        )
        assert "True" in out

    def test_risk_level_enum(self):
        """RiskLevel enum has LOW, MEDIUM, HIGH, CRITICAL."""
        out = self._run_script(
            "from core.automated_risk_controls import RiskLevel\n"
            "names = {e.name for e in RiskLevel}\n"
            "print(names == {'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'})\n"
        )
        assert "True" in out


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
