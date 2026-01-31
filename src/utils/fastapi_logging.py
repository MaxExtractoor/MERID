"""
MERID FastAPI Structured Logging Configuration
Provides JSON logging with correlation ID support
"""

import json
import logging
import sys
from datetime import datetime
from typing import Dict, Any
from pythonjsonlogger import jsonlogger


class StructuredFormatter(jsonlogger.JsonFormatter):
    """Custom JSON formatter with correlation ID support"""
    
    def add_fields(self, log_record: Dict[str, Any], record: logging.LogRecord, message_dict: Dict[str, Any]):
        super().add_fields(log_record, record, message_dict)
        
        # Add timestamp if not present
        if not log_record.get('timestamp'):
            log_record['timestamp'] = datetime.utcnow().isoformat() + 'Z'
        
        # Add service name
        log_record['service'] = 'merid-api'
        
        # Add correlation ID if available from request context
        if hasattr(record, 'correlation_id'):
            log_record['correlation_id'] = record.correlation_id


def setup_structured_logging():
    """Setup structured JSON logging for FastAPI"""
    
    # Remove existing handlers
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    
    # Create JSON formatter
    formatter = StructuredFormatter(
        '%(timestamp)s %(level)s %(name)s %(message)s'
    )
    
    # Create console handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    
    # Add handler to root logger
    root_logger.addHandler(handler)
    
    # Set log levels
    root_logger.setLevel(logging.INFO)
    
    # Enable debug logging for specific modules
    logging.getLogger("sqlalchemy.engine").setLevel(logging.DEBUG)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.DEBUG)
    logging.getLogger("merid.persistence").setLevel(logging.DEBUG)
    logging.getLogger("merid.service.phase0").setLevel(logging.DEBUG)
    logging.getLogger("merid.web.api.phase0").setLevel(logging.DEBUG)


class CorrelationLoggerAdapter(logging.LoggerAdapter):
    """Logger adapter that adds correlation ID to log records"""
    
    def process(self, msg, kwargs):
        # Add correlation ID to extra if available
        if 'extra' not in kwargs:
            kwargs['extra'] = {}
        
        if hasattr(self, 'correlation_id'):
            kwargs['extra']['correlation_id'] = self.correlation_id
        
        return msg, kwargs


def get_logger_with_correlation(correlation_id: str = None) -> logging.LoggerAdapter:
    """Get logger adapter with correlation ID"""
    logger = logging.getLogger("merid.api")
    adapter = CorrelationLoggerAdapter(logger, {})
    
    if correlation_id:
        adapter.correlation_id = correlation_id
    
    return adapter
