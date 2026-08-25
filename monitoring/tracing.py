"""
OpenTelemetry Distributed Tracing - Correlation ID propagation and request tracing.

This module implements distributed tracing with:
- OpenTelemetry instrumentation for FastAPI, HTTPX, and asyncio
- Correlation ID propagation across service boundaries
- Request tracing patterns for trading operations
- Dependency mapping and span relationships
- Configurable sampling and export settings

Version: 1.0.0
"""

from __future__ import annotations

import asyncio
import contextvars
import threading
from typing import Optional, Dict, Any, List
from contextlib import contextmanager, asynccontextmanager

from utils.logger import get_logger
from config.monitoring_config import get_monitoring_config, TracingConfig

logger = get_logger("monitoring.tracing")

# Global tracing state
_tracer = None
_provider = None
_tracing_initialized = False
_tracing_enabled = False

# Thread-safety: Lock for global singleton access
_tracing_lock = threading.Lock()


def init_tracing(config: Optional[TracingConfig] = None) -> None:
    """
    Initialize OpenTelemetry tracing with the given configuration.
    
    This function sets up the OpenTelemetry SDK with the appropriate exporter
    and instrumentation based on the configuration. It should be called once
    at application startup.
    
    Args:
        config: Tracing configuration (uses default if not provided)
    """
    global _tracer, _provider, _tracing_initialized, _tracing_enabled
    
    # Thread-safe initialization check
    with _tracing_lock:
        if _tracing_initialized:
            logger.warning("Tracing already initialized, skipping")
            return
        
        config = config or get_monitoring_config().tracing
        
        if not config.enabled:
            logger.info("Tracing is disabled in configuration")
            _tracing_enabled = False
            _tracing_initialized = True
            return
        
        try:
            from opentelemetry import trace
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
            from opentelemetry.sdk.resources import Resource, SERVICE_NAME
            
            # Create resource with service name
            resource = Resource.create({
                SERVICE_NAME: config.service_name,
                "service.version": "2.0.0",
                "deployment.environment": get_monitoring_config().environment.value,
            })
            
            # Create tracer provider
            provider = TracerProvider(resource=resource)
            
            # Configure exporter based on type
            if config.exporter == "jaeger":
                from opentelemetry.exporter.jaeger.thrift import JaegerExporter
                
                exporter = JaegerExporter(
                    agent_host_name=config.jaeger_host,
                    agent_port=config.jaeger_agent_port,
                    max_tag_value_length=config.max_span_size,
                )
                logger.info(f"Configured Jaeger exporter: {config.jaeger_host}:{config.jaeger_agent_port}")
            
            elif config.exporter == "otlp":
                from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
                
                exporter = OTLPSpanExporter(
                    endpoint=config.otlp_endpoint,
                    headers=config.otlp_headers,
                )
                logger.info(f"Configured OTLP exporter: {config.otlp_endpoint}")
            
            else:  # console or unknown
                from opentelemetry.sdk.trace.export import ConsoleSpanExporter
                exporter = ConsoleSpanExporter()
                logger.info("Configured console exporter")
            
            # Add batch span processor
            processor = BatchSpanProcessor(
                exporter,
                max_queue_size=config.batch_size,
                schedule_delay_millis=config.schedule_delay_millis,
            )
            provider.add_span_processor(processor)
            
            # Set global tracer provider
            trace.set_tracer_provider(provider)
            
            # Get tracer
            _tracer = trace.get_tracer(__name__)
            _provider = provider
            _tracing_enabled = True
            _tracing_initialized = True
            
            logger.info(f"OpenTelemetry tracing initialized (sample_rate={config.sample_rate})")
            
            # Configure instrumentation if enabled
            if config.instrument_fastapi:
                _instrument_fastapi(config)
            if config.instrument_httpx:
                _instrument_httpx(config)
            if config.instrument_asyncio:
                _instrument_asyncio(config)
            
        except ImportError as e:
            logger.warning(f"OpenTelemetry packages not installed: {e}")
            logger.info("Install with: pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-jaeger")
            _tracing_enabled = False
            _tracing_initialized = True
        except Exception as e:
            logger.error(f"Failed to initialize tracing: {e}")
            _tracing_enabled = False
            _tracing_initialized = True


def _instrument_fastapi(config: TracingConfig) -> None:
    """Instrument FastAPI for automatic request tracing."""
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware
        
        # Configure sampling
        from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
        sampler = TraceIdRatioBased(config.sample_rate)
        
        # Note: This should be called after FastAPI app is created
        # The actual instrumentation is done in the web/main.py module
        logger.info("FastAPI instrumentation configured")
    except ImportError:
        logger.warning("FastAPI instrumentation package not installed")


def _instrument_httpx(config: TracingConfig) -> None:
    """Instrument HTTPX for automatic HTTP client tracing."""
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        
        HTTPXClientInstrumentor().instrument()
        logger.info("HTTPX instrumentation configured")
    except ImportError:
        logger.warning("HTTPX instrumentation package not installed")


def _instrument_asyncio(config: TracingConfig) -> None:
    """Instrument asyncio for task tracing."""
    try:
        from opentelemetry.instrumentation.asyncio import AsyncIOInstrumentor
        
        AsyncIOInstrumentor().instrument()
        logger.info("AsyncIO instrumentation configured")
    except ImportError:
        logger.warning("AsyncIO instrumentation package not installed")


def get_tracer():
    """Get the global OpenTelemetry tracer."""
    if not _tracing_enabled or _tracer is None:
        return None
    return _tracer


def is_tracing_enabled() -> bool:
    """Check if tracing is enabled and initialized."""
    return _tracing_enabled and _tracing_initialized


@contextmanager
def start_span(
    name: str,
    attributes: Optional[Dict[str, Any]] = None,
    kind: Optional[str] = None,
):
    """
    Start a new span as a context manager.
    
    This is a synchronous context manager for creating spans in non-async code.
    For async code, use start_async_span instead.
    
    Args:
        name: Span name
        attributes: Span attributes (key-value pairs)
        kind: Span kind (client, server, producer, consumer, internal)
    
    Example:
        with start_span("database_query", {"db.name": "postgres", "db.operation": "SELECT"}):
            # Do work
            pass
    """
    if not is_tracing_enabled():
        yield None
        return
    
    from opentelemetry import trace
    
    # Convert kind string to SpanKind
    span_kind = None
    if kind:
        from opentelemetry.trace import SpanKind
        span_kind_map = {
            "client": SpanKind.CLIENT,
            "server": SpanKind.SERVER,
            "producer": SpanKind.PRODUCER,
            "consumer": SpanKind.CONSUMER,
            "internal": SpanKind.INTERNAL,
        }
        span_kind = span_kind_map.get(kind.lower())
    
    # Add correlation ID if propagation is enabled
    config = get_monitoring_config().tracing
    if config.propagate_correlation_id:
        from utils.logger import get_correlation_id
        cid = get_correlation_id()
        if cid and attributes:
            attributes["correlation_id"] = cid
        elif cid:
            attributes = {"correlation_id": cid}
    
    with _tracer.start_as_current_span(name, attributes=attributes, kind=span_kind) as span:
        yield span


@asynccontextmanager
async def start_async_span(
    name: str,
    attributes: Optional[Dict[str, Any]] = None,
    kind: Optional[str] = None,
):
    """
    Start a new span as an async context manager.
    
    This is for creating spans in async code.
    
    Args:
        name: Span name
        attributes: Span attributes (key-value pairs)
        kind: Span kind (client, server, producer, consumer, internal)
    
    Example:
        async with start_async_span("trading_order", {"venue": "kalshi", "side": "buy"}):
            # Do async work
            pass
    """
    if not is_tracing_enabled():
        yield None
        return
    
    from opentelemetry import trace
    
    # Convert kind string to SpanKind
    span_kind = None
    if kind:
        from opentelemetry.trace import SpanKind
        span_kind_map = {
            "client": SpanKind.CLIENT,
            "server": SpanKind.SERVER,
            "producer": SpanKind.PRODUCER,
            "consumer": SpanKind.CONSUMER,
            "internal": SpanKind.INTERNAL,
        }
        span_kind = span_kind_map.get(kind.lower())
    
    # Add correlation ID if propagation is enabled
    config = get_monitoring_config().tracing
    if config.propagate_correlation_id:
        from utils.logger import get_correlation_id
        cid = get_correlation_id()
        if cid and attributes:
            attributes["correlation_id"] = cid
        elif cid:
            attributes = {"correlation_id": cid}
    
    with _tracer.start_as_current_span(name, attributes=attributes, kind=span_kind) as span:
        yield span


def add_span_attributes(attributes: Dict[str, Any]) -> None:
    """
    Add attributes to the current span.
    
    Args:
        attributes: Dictionary of attributes to add
    """
    if not is_tracing_enabled():
        return
    
    from opentelemetry import trace
    current_span = trace.get_current_span()
    if current_span and current_span.is_recording():
        for key, value in attributes.items():
            current_span.set_attribute(key, value)


def add_span_event(name: str, attributes: Optional[Dict[str, Any]] = None) -> None:
    """
    Add an event to the current span.
    
    Events are timestamped annotations that can be used to mark specific
    points in time during a span's lifetime.
    
    Args:
        name: Event name
        attributes: Event attributes
    """
    if not is_tracing_enabled():
        return
    
    from opentelemetry import trace
    current_span = trace.get_current_span()
    if current_span and current_span.is_recording():
        current_span.add_event(name, attributes or {})


def record_exception(exception: Exception) -> None:
    """
    Record an exception on the current span.
    
    Args:
        exception: The exception to record
    """
    if not is_tracing_enabled():
        return
    
    from opentelemetry import trace
    current_span = trace.get_current_span()
    if current_span and current_span.is_recording():
        current_span.record_exception(exception)


def get_current_span_id() -> Optional[str]:
    """
    Get the current span ID.
    
    Returns:
        Span ID as a hex string, or None if no span is active
    """
    if not is_tracing_enabled():
        return None
    
    from opentelemetry import trace
    current_span = trace.get_current_span()
    if current_span:
        return format(current_span.context.span_id, "016x")
    return None


def get_current_trace_id() -> Optional[str]:
    """
    Get the current trace ID.
    
    Returns:
        Trace ID as a hex string, or None if no span is active
    """
    if not is_tracing_enabled():
        return None
    
    from opentelemetry import trace
    current_span = trace.get_current_span()
    if current_span:
        return format(current_span.context.trace_id, "032x")
    return None


def shutdown_tracing() -> None:
    """
    Shutdown the tracing provider.
    
    This should be called when the application is shutting down to ensure
    all spans are flushed to the exporter.
    """
    global _tracing_initialized, _tracing_enabled
    
    if _provider:
        _provider.shutdown()
        _tracing_initialized = False
        _tracing_enabled = False
        logger.info("OpenTelemetry tracing shutdown")


# Trading-specific tracing helpers

def trace_trading_operation(
    venue: str,
    operation: str,
    attributes: Optional[Dict[str, Any]] = None,
):
    """
    Context manager for tracing trading operations.
    
    This is a convenience wrapper for trading-specific spans with
    standard attributes for venue, operation type, etc.
    
    Args:
        venue: Trading venue (e.g., "kalshi", "binance")
        operation: Operation type (e.g., "place_order", "cancel_order", "get_position")
        attributes: Additional attributes
    
    Example:
        with trace_trading_operation("kalshi", "place_order", {"market_id": "BTC-15m"}):
            # Place order
            pass
    """
    span_attrs = {
        "trading.venue": venue,
        "trading.operation": operation,
    }
    if attributes:
        span_attrs.update(attributes)
    
    return start_span(f"trading.{operation}", span_attrs, kind="client")


async def trace_async_trading_operation(
    venue: str,
    operation: str,
    attributes: Optional[Dict[str, Any]] = None,
):
    """
    Async context manager for tracing trading operations.
    
    Async version of trace_trading_operation.
    """
    span_attrs = {
        "trading.venue": venue,
        "trading.operation": operation,
    }
    if attributes:
        span_attrs.update(attributes)
    
    return start_async_span(f"trading.{operation}", span_attrs, kind="client")


def trace_agent_decision(
    agent_id: str,
    decision_type: str,
    attributes: Optional[Dict[str, Any]] = None,
):
    """
    Context manager for tracing agent decision-making.
    
    Args:
        agent_id: Agent identifier
        decision_type: Type of decision (e.g., "market_analysis", "risk_assessment")
        attributes: Additional attributes
    
    Example:
        with trace_agent_decision("bull_analyst", "market_analysis", {"market": "BTC"}):
            # Agent makes decision
            pass
    """
    span_attrs = {
        "agent.id": agent_id,
        "agent.decision_type": decision_type,
    }
    if attributes:
        span_attrs.update(attributes)
    
    return start_span(f"agent.{decision_type}", span_attrs, kind="internal")
