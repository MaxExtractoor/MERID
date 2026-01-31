"""
MERID Phase 0 Structured Logging Configuration
Provides JSON logging with correlation IDs for acceptance testing
"""

import json
import logging
import uuid
import datetime
from typing import Dict, Any
from contextlib import contextmanager


class StructuredLogger:
    """JSON structured logger with correlation ID support"""
    
    def __init__(self, service_name: str = "merid-phase0"):
        self.service_name = service_name
        self.logger = logging.getLogger(service_name)
        self.logger.setLevel(logging.INFO)
        
        # Remove existing handlers
        self.logger.handlers.clear()
        
        # Add JSON handler
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter('%(message)s'))
        self.logger.addHandler(handler)
    
    def log(self, level: str, event: str, **fields: Any) -> None:
        """Emit structured log event"""
        payload = {
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "level": level.upper(),
            "service": self.service_name,
            "event": event,
            **fields
        }
        self.logger.info(json.dumps(payload))
    
    def info(self, event: str, **fields: Any) -> None:
        self.log("INFO", event, **fields)
    
    def debug(self, event: str, **fields: Any) -> None:
        self.log("DEBUG", event, **fields)
    
    def error(self, event: str, **fields: Any) -> None:
        self.log("ERROR", event, **fields)
    
    def warning(self, event: str, **fields: Any) -> None:
        self.log("WARNING", event, **fields)


@contextmanager
def correlation_context(test_id: str = None, correlation_id: str = None):
    """Context manager for correlation ID logging"""
    if test_id is None:
        test_id = f"phase0_acceptance_{datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
    
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())
    
    logger = StructuredLogger()
    
    logger.info("test_context_started", 
               test_id=test_id, 
               correlation_id=correlation_id)
    
    try:
        yield test_id, correlation_id, logger
    finally:
        logger.info("test_context_ended", 
                   test_id=test_id, 
                   correlation_id=correlation_id)


# Global logger instance
structured_logger = StructuredLogger()
