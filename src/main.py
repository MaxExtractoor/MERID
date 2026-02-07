"""
MERID FastAPI Application Setup
Configures structlog, correlation middleware, and SQL logging
"""

import os
from fastapi import FastAPI
from asgi_correlation_id import CorrelationIdMiddleware

from utils.structlog_config import configure_logging
from middleware.structlog_correlation import LogCorrelationIdMiddleware
from utils.sql_structlog import attach_sql_logging


def create_app() -> FastAPI:
    """Create FastAPI app with structured logging configuration"""
    
    # Configure structured logging first
    configure_logging()
    
    # Create FastAPI app
    app = FastAPI(
        title="MERID API",
        description="MERID Governance Platform API",
        version="1.0.0"
    )
    
    # Add correlation ID middleware
    app.add_middleware(CorrelationIdMiddleware)  # Creates X-Request-ID / correlation ID
    app.add_middleware(LogCorrelationIdMiddleware)  # Binds to structlog + logs requests
    
    # Configure SQL logging when database is available
    @app.on_event("startup")
    async def startup_event():
        """Configure SQL logging on startup"""
        try:
            # This would be called when you create your SQLAlchemy engine
            # attach_sql_logging(engine)
            pass
        except Exception as e:
            # Log error but don't fail startup
            import structlog
            logger = structlog.get_logger("app")
            logger.warning("sql_logging_setup_failed", error=str(e))
    
    return app


# Create app instance
app = create_app()


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    import structlog
    logger = structlog.get_logger("health")
    
    logger.info("health_check_called")
    return {"status": "healthy", "timestamp": "2026-01-24T22:25:00Z"}


if __name__ == "__main__":
    import uvicorn
    
    # Set environment for development
    os.environ.setdefault("APP_ENV", "dev")
    
    uvicorn.run(app, host="0.0.0.0", port=8001)
