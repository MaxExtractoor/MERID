"""
MERID Distributed Tracing Implementation
Gate 3: Service Reliability - Evidence Artifact
Date: 2026-01-26

Implements distributed tracing with correlation IDs for
tracking requests across services and agents.
"""

import asyncio
import os
from utils.logger import get_logger
import time
import uuid
from typing import Dict, Optional, Any
from contextlib import contextmanager
from functools import wraps
from dataclasses import dataclass, field

from opentelemetry import trace
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import SERVICE_NAME, RESOURCE
from opentelemetry.semconv.trace import SpanKind
from opentelemetry.trace import Span, Status, StatusCode
from opentelemetry import context as context_api

logger = get_logger(__name__)

@dataclass
class TraceContext:
    """Trace context for distributed tracing."""
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    span_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    parent_span_id: Optional[str] = None
    baggage: Dict[str, str] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, str]:
        """Convert to dictionary for headers."""
        return {
            "x-trace-id": self.trace_id,
            "x-span-id": self.span_id,
            "x-correlation-id": self.correlation_id,
            "x-parent-span-id": self.parent_span_id or "",
        }


class TracingManager:
    """
    Manages distributed tracing across MERID services.
    """
    
    def __init__(self, service_name: str = "merid-api"):
        self.service_name = service_name
        self.tracer_provider = None
        self.tracer = None
        self._setup_tracing()
        
    def _setup_tracing(self):
        """Initialize OpenTelemetry tracing."""
        try:
            # Configure Jaeger exporter — host/port from env so containerised deploys work
            jaeger_exporter = JaegerExporter(
                agent_host_name=os.getenv("JAEGER_AGENT_HOST", "localhost"),
                agent_port=int(os.getenv("JAEGER_AGENT_PORT", "6831")),
            )
            
            # Set up trace provider
            self.tracer_provider = TracerProvider(
                resource=RESOURCE.create(
                    {SERVICE_NAME: self.service_name}
                )
            )
            
            # Add span processor
            span_processor = BatchSpanProcessor(jaeger_exporter)
            self.tracer_provider.add_span_processor(span_processor)
            
            # Set global tracer
            trace.set_tracer_provider(self.tracer_provider)
            self.tracer = trace.get_tracer(__name__)
            
            logger.info(f"Tracing initialized for {self.service_name}")
            
        except Exception as e:
            logger.warning(f"Failed to initialize tracing: {e}")
            self.tracer = trace.get_tracer(__name__)
    
    def create_span(
        self, 
        name: str, 
        kind: SpanKind = SpanKind.INTERNAL,
        parent_context: Optional[TraceContext] = None
    ) -> Span:
        """Create a new span with optional parent context."""
        if parent_context:
            context = trace.set_span_in_context(
                parent_context.to_dict(),
                trace.SpanContext(
                    trace_id=int(parent_context.trace_id.replace('-', '',)),
                    span_id=int(parent_context.span_id.replace('-', '',)),
                    is_remote=False
                )
            )
        else:
            context = {}
            
        span = self.tracer.start_span(name, kind=kind)
        return span
    
    @contextmanager
    def trace_operation(
        self, 
        operation_name: str, 
        attributes: Optional[Dict[str, Any]] = None
    ):
        """Context manager for tracing operations."""
        span = self.create_span(operation_name)
        if attributes:
            for key, value in attributes.items():
                span.set_attribute(key, value)
        
        try:
            yield span
            span.set_status(Status(StatusCode.OK))
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            raise
        finally:
            span.end()
    
    def extract_context_from_headers(self, headers: Dict[str, str]) -> TraceContext:
        """Extract trace context from HTTP headers."""
        return TraceContext(
            trace_id=headers.get("x-trace-id", str(uuid.uuid4())),
            span_id=headers.get("x-span-id", str(uuid.uuid4())),
            correlation_id=headers.get("x-correlation-id", str(uuid.uuid4())),
            parent_span_id=headers.get("x-parent-span-id"),
        )
    
    def inject_context_into_headers(self, context: TraceContext) -> Dict[str, str]:
        """Inject trace context into HTTP headers."""
        return context.to_dict()


# Global tracing manager
tracing_manager = TracingManager()


def trace_async(operation_name: str):
    """
    Decorator for async function tracing.
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            
            with tracing_manager.trace_operation(operation_name) as span:
                span.set_attribute("function.name", func.__name__)
                span.set_attribute("function.module", func.__module__)
                
                try:
                    result = await func(*args, **kwargs)
                    span.set_attribute("success", True)
                    return result
                except Exception as e:
                    span.set_attribute("success", False)
                    span.set_attribute("error.type", type(e).__name__)
                    raise
                finally:
                    duration = time.time() - start_time
                    span.set_attribute("duration_ms", duration * 1000)
        
        return wrapper
    return decorator


class CorrelationMiddleware:
    """
    FastAPI middleware for correlation ID management.
    """
    
    def __init__(self, app):
        self.app = app
        self.app.middleware("http")(self.middleware)
    
    async def middleware(self, request, call_next):
        """Add correlation ID to request and response headers."""
        # Extract or create correlation ID
        correlation_id = request.headers.get("x-correlation-id")
        if not correlation_id:
            correlation_id = str(uuid.uuid4())
        
        # Store in request state
        request.state.correlation_id = correlation_id
        
        # Process request
        response = await call_next(request)
        
        # Add correlation ID to response headers
        response.headers["x-correlation-id"] = correlation_id
        
        return response


class AgentTracer:
    """
    Specialized tracer for agent operations.
    """
    
    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self.tracer = trace.get_tracer(f"agent.{agent_id}")
    
    @contextmanager
    def trace_agent_decision(
        self, 
        decision_type: str, 
        inputs: Dict[str, Any],
        confidence: Optional[float] = None
    ):
        """Trace agent decision-making process."""
        span_name = f"agent.{self.agent_id}.{decision_type}"
        
        with tracing_manager.trace_operation(span_name) as span:
            span.set_attribute("agent.id", self.agent_id)
            span.set_attribute("decision.type", decision_type)
            span.set_attribute("decision.inputs", str(inputs))
            
            if confidence is not None:
                span.set_attribute("decision.confidence", confidence)
            
            try:
                yield span
                span.set_attribute("decision.outcome", "success")
            except Exception as e:
                span.set_attribute("decision.outcome", "error")
                span.set_attribute("decision.error", str(e))
                raise
    
    def trace_agent_execution(self, execution_id: str, action: str):
        """Create a span for agent execution."""
        span = self.tracer.start_span(f"agent.{self.agent_id}.execution")
        span.set_attribute("agent.id", self.agent_id)
        span.set_attribute("execution.id", execution_id)
        span.set_attribute("execution.action", action)
        return span


# Example usage for critical paths
@trace_async("market_data_fetch")
async def fetch_market_data_with_tracing(symbol: str) -> dict:
    """Fetch market data with distributed tracing."""
    # Implementation would go here
    pass

@trace_async("order_submission")
async def submit_order_with_tracing(order_data: dict) -> dict:
    """Submit order with distributed tracing."""
    # Implementation would go here
    pass

# Agent tracing example
def trace_agent_decision(agent_id: str, decision_type: str, inputs: Dict[str, Any]):
    """Helper function for agent decision tracing."""
    tracer = AgentTracer(agent_id)
    return tracer.trace_agent_decision(decision_type, inputs)
