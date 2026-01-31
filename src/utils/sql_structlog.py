"""
MERID SQLAlchemy Structured Logging
Captures SQL queries with duration and parameters in structlog
"""

import time
import structlog
from sqlalchemy import event
from sqlalchemy.engine import Engine

sql_log = structlog.get_logger("sql")


def attach_sql_logging(engine: Engine):
    """Attach structured logging to SQLAlchemy engine events"""
    
    @event.listens_for(engine, "before_cursor_execute")
    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        context._query_start_time = time.perf_counter()
        sql_log.debug("sql_start", statement=statement, params=parameters)

    @event.listens_for(engine, "after_cursor_execute")
    def after_cursor_execute(conn, cursor, statement, parameters, context, rowcount):
        start = getattr(context, "_query_start_time", None)
        duration_ms = None
        if start is not None:
            duration_ms = (time.perf_counter() - start) * 1000

        sql_log.info(
            "sql_end",
            statement=statement,
            params=parameters,
            duration_ms=round(duration_ms, 3) if duration_ms is not None else None,
            rowcount=rowcount,
        )

    @event.listens_for(engine, "handle_error")
    def handle_error(exception, context):
        sql_log.error(
            "sql_error",
            statement=getattr(context, 'statement', None),
            params=getattr(context, 'parameters', None),
            exception=str(exception),
            exception_type=type(exception).__name__,
        )


def log_decision_persistence_attempt(model_id: str, has_performance_data: bool, decision_data: dict):
    """Log decision persistence attempt"""
    log = structlog.get_logger("persistence")
    
    log.info(
        "decision_persistence_attempt",
        model_id=model_id,
        has_performance_data=has_performance_data,
        decision_data=decision_data,
    )


def log_decision_persistence_success(model_id: str, decision_id: str, metrics_state: str):
    """Log successful decision persistence"""
    log = structlog.get_logger("persistence")
    
    log.info(
        "decision_persistence_success",
        model_id=model_id,
        decision_id=decision_id,
        metrics_state=metrics_state,
    )


def log_decision_persistence_failure(model_id: str, error: str, error_type: str):
    """Log failed decision persistence"""
    log = structlog.get_logger("persistence")
    
    log.error(
        "decision_persistence_failure",
        model_id=model_id,
        error=error,
        error_type=error_type,
    )
