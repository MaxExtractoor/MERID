"""
MERID Swarm Tracing Infrastructure - MVP
Provides distributed tracing for agent operations and cascade detection.
"""

import uuid
import time
import threading
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict, deque
import json

from utils.logger import get_logger

logger = get_logger("swarm.tracing")


class SpanType(Enum):
    """Types of spans for distributed tracing"""
    TASK_ROOT = "task_root"
    AGENT_EXECUTION = "agent_execution"
    AGENT_MESSAGE = "agent_message"
    TOOL_CALL = "tool_call"
    STATE_READ = "state_read"
    STATE_WRITE = "state_write"


class SpanStatus(Enum):
    """Span status"""
    STARTED = "started"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass
class Span:
    """Distributed tracing span"""
    span_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    parent_span_id: Optional[str] = None
    span_type: SpanType = SpanType.TASK_ROOT
    agent_id: Optional[str] = None
    operation_name: str = ""
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    status: SpanStatus = SpanStatus.STARTED
    tags: Dict[str, Any] = field(default_factory=dict)
    events: List[Dict[str, Any]] = field(default_factory=list)
    
    def finish(self, status: SpanStatus = SpanStatus.COMPLETED):
        """Finish the span"""
        self.end_time = time.time()
        self.status = status
        logger.debug(f"Span finished: {self.span_id} ({self.span_type.value}) - {status.value}")
    
    def add_event(self, name: str, attributes: Dict[str, Any] = None):
        """Add event to span"""
        event = {
            "name": name,
            "timestamp": time.time(),
            "attributes": attributes or {}
        }
        self.events.append(event)
    
    def set_tag(self, key: str, value: Any):
        """Set tag on span"""
        self.tags[key] = value


class Tracer:
    """Distributed tracer for MERID swarm"""
    
    def __init__(self):
        self.active_spans: Dict[str, Span] = {}
        self.completed_spans: List[Span] = []
        self.trace_store: Dict[str, List[Span]] = defaultdict(list)
        self._lock = threading.RLock()
    
    def start_span(self, span_type: SpanType, operation_name: str,
                   parent_span_id: Optional[str] = None,
                   agent_id: Optional[str] = None,
                   trace_id: Optional[str] = None) -> Span:
        """Start a new span"""
        span = Span(
            span_type=span_type,
            operation_name=operation_name,
            parent_span_id=parent_span_id,
            agent_id=agent_id,
            trace_id=trace_id or str(uuid.uuid4())
        )
        
        with self._lock:
            self.active_spans[span.span_id] = span
            self.trace_store[span.trace_id].append(span)
        
        logger.debug(f"Started span: {span.span_id} ({span_type.value}) - {operation_name}")
        return span
    
    def finish_span(self, span_id: str, status: SpanStatus = SpanStatus.COMPLETED):
        """Finish a span"""
        with self._lock:
            span = self.active_spans.get(span_id)
            if span:
                span.finish(status)
                self.completed_spans.append(span)
                del self.active_spans[span_id]
            else:
                logger.debug(f"Span not found: {span_id}")
    
    def get_trace(self, trace_id: str) -> List[Span]:
        """Get all spans for a trace"""
        with self._lock:
            return self.trace_store.get(trace_id, []).copy()
    
    def get_active_spans(self) -> List[Span]:
        """Get all active spans"""
        with self._lock:
            return list(self.active_spans.values())
    
    def cleanup_completed(self, max_age_seconds: int = 3600):
        """Clean up old completed spans"""
        cutoff_time = time.time() - max_age_seconds
        with self._lock:
            self.completed_spans = [
                span for span in self.completed_spans 
                if span.end_time and span.end_time > cutoff_time
            ]


# Global tracer instance
tracer = Tracer()


class SpanContext:
    """Context manager for automatic span management"""
    
    def __init__(self, span_type: SpanType, operation_name: str,
                 parent_span_id: Optional[str] = None,
                 agent_id: Optional[str] = None,
                 trace_id: Optional[str] = None):
        self.span_type = span_type
        self.operation_name = operation_name
        self.parent_span_id = parent_span_id
        self.agent_id = agent_id
        self.trace_id = trace_id
        self.span: Optional[Span] = None
    
    def __enter__(self) -> Span:
        self.span = tracer.start_span(
            span_type=self.span_type,
            operation_name=self.operation_name,
            parent_span_id=self.parent_span_id,
            agent_id=self.agent_id,
            trace_id=self.trace_id
        )
        return self.span
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.span:
            if exc_type:
                self.span.finish(SpanStatus.FAILED)
                self.span.set_tag("error", True)
                self.span.set_tag("error_type", exc_type.__name__)
            else:
                self.span.finish(SpanStatus.COMPLETED)


# Decorator for automatic tracing
def trace_span(span_type: SpanType, operation_name: str = None):
    """Decorator for automatic span tracing"""
    def decorator(func: Callable):
        def wrapper(*args, **kwargs):
            func_name = operation_name or f"{func.__module__}.{func.__name__}"
            
            # Try to extract agent_id from first argument if it's an object with agent_id
            agent_id = None
            if args and hasattr(args[0], 'agent_id'):
                agent_id = args[0].agent_id
            
            # Try to get parent span from context
            parent_span_id = None
            current_span = getattr(wrapper, '_current_span', None)
            if current_span:
                parent_span_id = current_span.span_id
            
            with SpanContext(span_type, func_name, parent_span_id, agent_id) as span:
                wrapper._current_span = span
                try:
                    result = func(*args, **kwargs)
                    span.set_tag("success", True)
                    return result
                except Exception as e:
                    span.set_tag("success", False)
                    span.set_tag("error_message", str(e))
                    raise
                finally:
                    wrapper._current_span = None
        
        return wrapper
    return decorator
