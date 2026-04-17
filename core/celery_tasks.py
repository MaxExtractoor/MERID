"""Celery task configuration for MERID async workflows."""

import os
import time
from typing import Any, Dict

import structlog
from celery import Celery
from celery.signals import task_failure, task_success

logger = structlog.get_logger(__name__)

# Load Redis URLs from environment or settings
_redis_broker = os.environ.get("MERID_REDIS_BROKER_URL", "redis://localhost:6379/0")
_redis_backend = os.environ.get("MERID_REDIS_BACKEND_URL", "redis://localhost:6379/1")

# Attempt to use settings if available (for more complex config)
try:
    from merid.settings import settings
    if hasattr(settings, "REDIS_URL") and settings.REDIS_URL:
        _redis_broker = settings.REDIS_URL
        _redis_backend = (
            settings.REDIS_URL.replace("/0", "/1")
            if settings.REDIS_URL.endswith("/0")
            else settings.REDIS_URL + "/1"
        )
except Exception:
    pass  # Fall back to env var or localhost defaults

# Celery app configuration
celery_app = Celery(
    "merid",
    broker=_redis_broker,
    backend=_redis_backend,
    include=[
        "core.celery_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,  # 5 minutes
    worker_prefetch_multiplier=1,
    worker_concurrency=4,
)


@task_success.connect
def task_success_handler(sender=None, result=None, **kwargs):
    """Log successful task completion."""
    logger.info("task_completed", task=sender.name, task_id=sender.request.id)


@task_failure.connect
def task_failure_handler(sender=None, exception=None, **kwargs):
    """Log task failure."""
    logger.error(
        "task_failed",
        task=sender.name,
        task_id=sender.request.id,
        error=str(exception),
    )


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def run_backtest(
    self,
    strategy_id: str,
    start_date: str,
    end_date: str,
    parameters: Dict[str, Any],
):
    """Run trading strategy backtest asynchronously.

    Returns a deterministic placeholder payload until the real engine is wired.
    """
    time.sleep(0)
    logger.warning(
        "run_backtest_stub",
        strategy_id=strategy_id,
        message="Using stub backtask result — replace with real backtest engine before production",
    )
    return {
        "strategy_id": strategy_id,
        "start_date": start_date,
        "end_date": end_date,
        "sharpe_ratio": 0.0,
        "max_drawdown": 0.0,
        "parameters": parameters,
    }


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30)
def calculate_risk_metrics(self, portfolio_id: str):
    """Calculate portfolio risk metrics asynchronously (stub for CI/tests)."""
    time.sleep(0)
    logger.warning(
        "calculate_risk_metrics_stub",
        portfolio_id=portfolio_id,
    )
    return {
        "portfolio_id": portfolio_id,
        "var_95": 0.0,
        "cvar_95": 0.0,
    }


@celery_app.task(bind=True, max_retries=1)
def sync_market_data(self, symbols: list, timeframe: str = "1d"):
    """Sync historical market data asynchronously (stub)."""
    time.sleep(0)
    logger.warning("sync_market_data_stub", symbols=symbols, timeframe=timeframe)
    return {
        "symbols": symbols,
        "timeframe": timeframe,
        "status": "completed",
    }


@celery_app.task(bind=True, max_retries=5, default_retry_delay=10)
def submit_order_with_retry(self, order_params: Dict[str, Any]):
    """Submit order with automatic retry logic (not wired — stub)."""
    logger.error(
        "ORDER_SUBMISSION_NOT_IMPLEMENTED",
        order_id=order_params.get("client_order_id"),
    )
    raise NotImplementedError(
        f"Order submission not wired for order {order_params.get('client_order_id')}"
    )


@celery_app.task
def cleanup_old_data(days_to_keep: int = 30):
    """Cleanup old data records (stub)."""
    time.sleep(0)
    logger.warning("cleanup_old_data_stub", days_to_keep=days_to_keep)
    return {"records_deleted": 1000, "days_kept": days_to_keep}


# Workflow chains
def create_backtest_workflow(strategy_id: str, start_date: str, end_date: str):
    """Create a workflow chain for complete backtest analysis."""
    return run_backtest.s(strategy_id, start_date, end_date, {}) | calculate_risk_metrics.s()


def create_order_workflow(order_params: Dict[str, Any]):
    """Create order submission workflow with post-trade risk update."""
    return (
        submit_order_with_retry.s(order_params)
        | calculate_risk_metrics.si(order_params.get("portfolio_id", "default"))
    )
