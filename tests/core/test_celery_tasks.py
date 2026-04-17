"""Tests for core/celery_tasks.py."""
import pytest
from unittest.mock import Mock, patch
from core.celery_tasks import (
    celery_app, run_backtest, calculate_risk_metrics,
    sync_market_data, submit_order_with_retry, cleanup_old_data,
    create_backtest_workflow, create_order_workflow,
    task_success_handler, task_failure_handler
)


class TestCeleryApp:
    """Test Celery app configuration."""

    def test_app_exists(self):
        """Test celery app exists."""
        assert celery_app is not None

    def test_app_name(self):
        """Test celery app name."""
        assert celery_app.main == "merid"

    def test_serializer_config(self):
        """Test serializer configuration."""
        assert celery_app.conf.task_serializer == "json"
        assert celery_app.conf.accept_content == ["json"]


class TestTaskHandlers:
    """Test task signal handlers."""

    def test_task_success_handler(self):
        """Test task success handler logging."""
        sender = Mock()
        sender.name = "test_task"
        sender.request.id = "task_123"
        # Should not raise
        task_success_handler(sender=sender, result={})

    def test_task_failure_handler(self):
        """Test task failure handler logging."""
        sender = Mock()
        sender.name = "test_task"
        sender.request.id = "task_123"
        # Should not raise
        task_failure_handler(sender=sender, exception=Exception("test error"))


class TestRunBacktest:
    """Test run_backtest task."""

    @patch('core.celery_tasks.time.sleep', return_value=None)
    def test_run_backtest_success(self, mock_sleep):
        """Test successful backtest execution."""
        result = run_backtest.run(
            strategy_id="strat_1",
            start_date="2024-01-01",
            end_date="2024-01-31",
            parameters={},
        )
        assert result["strategy_id"] == "strat_1"
        assert "sharpe_ratio" in result
        assert "max_drawdown" in result


class TestCalculateRiskMetrics:
    """Test calculate_risk_metrics task."""

    @patch('core.celery_tasks.time.sleep', return_value=None)
    def test_calculate_risk_metrics(self, mock_sleep):
        """Test risk metrics calculation."""
        result = calculate_risk_metrics.run(portfolio_id="portfolio_1")
        assert result["portfolio_id"] == "portfolio_1"
        assert "var_95" in result
        assert "cvar_95" in result


class TestSyncMarketData:
    """Test sync_market_data task."""

    @patch('core.celery_tasks.time.sleep', return_value=None)
    def test_sync_market_data(self, mock_sleep):
        """Test market data sync."""
        result = sync_market_data.run(
            symbols=["BTC", "ETH"],
            timeframe="1d",
        )
        assert result["symbols"] == ["BTC", "ETH"]
        assert result["timeframe"] == "1d"
        assert result["status"] == "completed"


class TestCleanupOldData:
    """Test cleanup_old_data task."""

    @patch('core.celery_tasks.time.sleep', return_value=None)
    def test_cleanup_old_data(self, mock_sleep):
        """Test data cleanup."""
        result = cleanup_old_data.run(days_to_keep=30)
        assert result["records_deleted"] == 1000
        assert result["days_kept"] == 30


class TestWorkflowChains:
    """Test workflow chain creation."""

    def test_create_backtest_workflow(self):
        """Test backtest workflow chain creation."""
        workflow = create_backtest_workflow("strat_1", "2024-01-01", "2024-01-31")
        assert workflow is not None

    def test_create_order_workflow(self):
        """Test order workflow chain creation."""
        workflow = create_order_workflow({"symbol": "BTC", "side": "buy"})
        assert workflow is not None
