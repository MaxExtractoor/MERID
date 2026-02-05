"""Celery task configuration for MERID async workflows."""

from celery import Celery
from celery.signals import task_failure, task_success
from typing import Dict, Any
import structlog

logger = structlog.get_logger(__name__)

# Celery app configuration
celery_app = Celery(
    "merid",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/1",
    include=[
        "core.celery_tasks",
    ]
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
        error=str(exception)
    )


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def run_backtest(self, strategy_id: str, start_date: str, end_date: str, parameters: Dict[str, Any]):
    """Run trading strategy backtest asynchronously."""
    try:
        logger.info(
            "backtest_started",
            strategy_id=strategy_id,
            start=start_date,
            end=end_date
        )
        
        # Simulate backtest execution
        import time
        time.sleep(2)  # Placeholder for actual backtest
        
        results = {
            "strategy_id": strategy_id,
            "sharpe_ratio": 1.5,
            "max_drawdown": 0.15,
            "total_return": 0.25,
            "trades": 150
        }
        
        logger.info("backtest_completed", strategy_id=strategy_id)
        return results
        
    except Exception as exc:
        logger.error("backtest_failed", strategy_id=strategy_id, error=str(exc))
        raise self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30)
def calculate_risk_metrics(self, portfolio_id: str):
    """Calculate portfolio risk metrics asynchronously."""
    try:
        logger.info("risk_calculation_started", portfolio_id=portfolio_id)
        
        # Simulate risk calculation
        import time
        time.sleep(1)
        
        metrics = {
            "portfolio_id": portfolio_id,
            "var_95": 5000.0,
            "cvar_95": 7500.0,
            "beta": 1.1,
            "volatility": 0.25
        }
        
        logger.info("risk_calculation_completed", portfolio_id=portfolio_id)
        return metrics
        
    except Exception as exc:
        logger.error("risk_calculation_failed", portfolio_id=portfolio_id, error=str(exc))
        raise self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=1)
def sync_market_data(self, symbols: list, timeframe: str = "1d"):
    """Sync historical market data asynchronously."""
    try:
        logger.info("market_data_sync_started", symbols=symbols, timeframe=timeframe)
        
        # Simulate data sync
        import time
        time.sleep(3)
        
        result = {
            "symbols": symbols,
            "timeframe": timeframe,
            "records_synced": len(symbols) * 1000,
            "status": "completed"
        }
        
        logger.info("market_data_sync_completed", symbols=symbols)
        return result
        
    except Exception as exc:
        logger.error("market_data_sync_failed", symbols=symbols, error=str(exc))
        raise self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=5, default_retry_delay=10)
def submit_order_with_retry(self, order_params: Dict[str, Any]):
    """Submit order with automatic retry logic."""
    try:
        logger.info("order_submission_started", order_id=order_params.get("client_order_id"))
        
        # Simulate order submission
        import time
        time.sleep(0.5)
        
        # Simulate occasional failure for retry testing
        import random
        if random.random() < 0.3:  # 30% failure rate for testing
            raise Exception("Temporary network error")
        
        result = {
            "order_id": f"order_{hash(str(order_params))}",
            "status": "submitted",
            "params": order_params
        }
        
        logger.info("order_submission_completed", order_id=result["order_id"])
        return result
        
    except Exception as exc:
        logger.warning("order_submission_retrying", error=str(exc), retry_count=self.request.retries)
        raise self.retry(exc=exc, countdown=10 * (self.request.retries + 1))


@celery_app.task
def cleanup_old_data(days_to_keep: int = 30):
    """Cleanup old data records."""
    logger.info("cleanup_started", days_to_keep=days_to_keep)
    
    # Simulate cleanup
    import time
    time.sleep(1)
    
    result = {"records_deleted": 1000, "days_kept": days_to_keep}
    logger.info("cleanup_completed", result=result)
    return result


# Workflow chains
def create_backtest_workflow(strategy_id: str, start_date: str, end_date: str):
    """Create a workflow chain for complete backtest analysis."""
    return (
        run_backtest.s(strategy_id, start_date, end_date, {})
        | calculate_risk_metrics.s()
    )


def create_order_workflow(order_params: Dict[str, Any]):
    """Create order submission workflow with post-trade risk update."""
    return (
        submit_order_with_retry.s(order_params)
        | calculate_risk_metrics.si(order_params.get("portfolio_id", "default"))
    )
