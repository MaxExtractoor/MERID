"""Tests for frontend telemetry API: ingest, batch, recent buffer, SLI counters.

Covers:
- Single event ingestion (POST /api/v1/telemetry)
- Batch ingestion (POST /api/v1/telemetry/batch)
- Recent events ring buffer (GET /api/v1/telemetry/recent)
- SLI counters and reset (GET /api/v1/telemetry/sli, POST /api/v1/telemetry/sli/reset)
- Correlation ID propagation
- Validation of required fields
"""

import logging

import pytest

from web.api.telemetry import (
    UiLogEntry,
    UiLogBatch,
    _UI_ERROR_BUFFER,
    _sli,
    _ingest,
    router,
)


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clean_state():
    """Reset ring buffer and SLI counters before each test."""
    _UI_ERROR_BUFFER.clear()
    _sli.reset()
    yield
    _UI_ERROR_BUFFER.clear()
    _sli.reset()


def _make_entry(**overrides) -> UiLogEntry:
    """Build a UiLogEntry with sensible defaults."""
    defaults = {
        "level": "error",
        "component": "TestComponent",
        "message": "Something failed",
        "timestamp": "2026-02-13T22:00:00.000Z",
    }
    defaults.update(overrides)
    return UiLogEntry(**defaults)


# ── UiLogEntry model tests ───────────────────────────────────────────

class TestUiLogEntryModel:
    """Pydantic model validation for UiLogEntry."""

    def test_minimal_entry(self):
        entry = UiLogEntry(level="error", component="X", message="fail")
        assert entry.level == "error"
        assert entry.component == "X"
        assert entry.error is None
        assert entry.stack is None
        assert entry.context is None

    def test_full_entry(self):
        entry = UiLogEntry(
            level="warn",
            component="TopBar",
            message="PnL fetch failed",
            error="NetworkError",
            stack="at fetch (TopBar.tsx:29)",
            context={"endpoint": "/portfolio"},
            timestamp="2026-02-13T22:00:00.000Z",
            correlation_id="abc-123",
        )
        assert entry.error == "NetworkError"
        assert entry.context == {"endpoint": "/portfolio"}
        assert entry.correlation_id == "abc-123"

    def test_missing_required_fields(self):
        with pytest.raises(Exception):
            UiLogEntry(level="error")  # missing component, message


# ── _ingest function tests ───────────────────────────────────────────

class TestIngest:
    """Direct tests of the _ingest helper."""

    def test_error_buffered(self):
        entry = _make_entry(level="error")
        record = _ingest(entry)
        assert len(_UI_ERROR_BUFFER) == 1
        assert record["level"] == "error"
        assert "server_ts" in record
        assert "correlation_id" in record

    def test_warn_buffered(self):
        entry = _make_entry(level="warn", message="Stub data in use")
        _ingest(entry)
        assert len(_UI_ERROR_BUFFER) == 1

    def test_info_not_buffered(self):
        entry = _make_entry(level="info", message="Reconnected")
        _ingest(entry)
        assert len(_UI_ERROR_BUFFER) == 0

    def test_correlation_id_passthrough(self):
        entry = _make_entry()
        record = _ingest(entry, correlation_id="custom-cid-42")
        assert record["correlation_id"] == "custom-cid-42"

    def test_correlation_id_from_entry(self):
        entry = _make_entry(correlation_id="entry-cid")
        record = _ingest(entry)
        assert record["correlation_id"] == "entry-cid"

    def test_correlation_id_generated_when_missing(self):
        entry = _make_entry()
        record = _ingest(entry)
        assert record["correlation_id"]  # non-empty UUID string
        assert len(record["correlation_id"]) > 10


# ── SLI counter tests ────────────────────────────────────────────────

class TestSliCounters:
    """SLI counter accumulation and snapshot."""

    def test_error_counted(self):
        _ingest(_make_entry(level="error", component="A"))
        _ingest(_make_entry(level="error", component="A"))
        _ingest(_make_entry(level="error", component="B"))
        snap = _sli.snapshot()
        assert snap["error_count"] == 3
        assert snap["total_events"] == 3
        assert snap["top_error_components"][0]["component"] == "A"
        assert snap["top_error_components"][0]["count"] == 2

    def test_warn_counted(self):
        _ingest(_make_entry(level="warn"))
        snap = _sli.snapshot()
        assert snap["warn_count"] == 1
        assert snap["error_count"] == 0

    def test_info_counted(self):
        _ingest(_make_entry(level="info"))
        snap = _sli.snapshot()
        assert snap["info_count"] == 1

    def test_error_rate(self):
        for _ in range(10):
            _ingest(_make_entry(level="error"))
        snap = _sli.snapshot()
        assert snap["error_rate_per_sec"] > 0

    def test_reset(self):
        _ingest(_make_entry(level="error"))
        _sli.reset()
        snap = _sli.snapshot()
        assert snap["total_events"] == 0
        assert snap["error_count"] == 0

    def test_top_components_limited_to_10(self):
        for i in range(15):
            _ingest(_make_entry(level="error", component=f"Comp{i}"))
        snap = _sli.snapshot()
        assert len(snap["top_error_components"]) == 10


# ── Ring buffer tests ────────────────────────────────────────────────

class TestRingBuffer:
    """Ring buffer capacity and ordering."""

    def test_buffer_max_size(self):
        for i in range(600):
            _ingest(_make_entry(level="error", message=f"err-{i}"))
        assert len(_UI_ERROR_BUFFER) == 500  # maxlen

    def test_newest_last(self):
        _ingest(_make_entry(level="error", message="first"))
        _ingest(_make_entry(level="error", message="second"))
        assert _UI_ERROR_BUFFER[-1]["message"] == "second"


# ── Batch model tests ────────────────────────────────────────────────

class TestBatchModel:
    """UiLogBatch validation."""

    def test_batch_creation(self):
        batch = UiLogBatch(entries=[
            _make_entry().model_dump(),
            _make_entry(level="warn", message="warning").model_dump(),
        ])
        assert len(batch.entries) == 2

    def test_empty_batch(self):
        batch = UiLogBatch(entries=[])
        assert len(batch.entries) == 0


# ── JSON formatter tests ─────────────────────────────────────────────

class TestJsonFormatter:
    """Structured JSON log formatter with correlation ID."""

    def test_json_output_is_valid(self):
        import json as _json
        from utils.logger import JsonFormatter
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test.logger", level=logging.ERROR, pathname="", lineno=0,
            msg="Something broke", args=(), exc_info=None,
        )
        output = formatter.format(record)
        parsed = _json.loads(output)
        assert parsed["level"] == "ERROR"
        assert parsed["logger"] == "test.logger"
        assert parsed["message"] == "Something broke"
        assert "ts" in parsed

    def test_correlation_id_included_when_set(self):
        import json as _json
        from utils.logger import JsonFormatter, set_correlation_id, correlation_id_var
        formatter = JsonFormatter()
        token = set_correlation_id("test-cid-999")
        try:
            record = logging.LogRecord(
                name="test", level=logging.INFO, pathname="", lineno=0,
                msg="hello", args=(), exc_info=None,
            )
            output = formatter.format(record)
            parsed = _json.loads(output)
            assert parsed["correlation_id"] == "test-cid-999"
        finally:
            correlation_id_var.reset(token)

    def test_correlation_id_absent_when_not_set(self):
        import json as _json
        from utils.logger import JsonFormatter
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello", args=(), exc_info=None,
        )
        output = formatter.format(record)
        parsed = _json.loads(output)
        assert "correlation_id" not in parsed

    def test_extra_fields_preserved(self):
        import json as _json
        from utils.logger import JsonFormatter
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="req", args=(), exc_info=None,
        )
        record.endpoint = "/api/v1/test"
        record.duration_ms = 42.5
        output = formatter.format(record)
        parsed = _json.loads(output)
        assert parsed["endpoint"] == "/api/v1/test"
        assert parsed["duration_ms"] == 42.5


# ── Correlation ID contextvars tests ─────────────────────────────────

class TestCorrelationIdContext:
    """contextvars-based correlation ID management."""

    def test_get_returns_none_by_default(self):
        from utils.logger import get_correlation_id
        assert get_correlation_id() is None

    def test_set_and_get(self):
        from utils.logger import set_correlation_id, get_correlation_id, correlation_id_var
        token = set_correlation_id("abc-123")
        try:
            assert get_correlation_id() == "abc-123"
        finally:
            correlation_id_var.reset(token)

    def test_reset_clears(self):
        from utils.logger import set_correlation_id, get_correlation_id, correlation_id_var
        token = set_correlation_id("abc-123")
        correlation_id_var.reset(token)
        assert get_correlation_id() is None


# ── Prometheus metrics format tests ──────────────────────────────────

class TestPrometheusMetrics:
    """Prometheus exposition format output."""

    def test_metrics_output_format(self):
        from web.api.telemetry import prometheus_metrics
        import asyncio
        # Ingest some events first
        _ingest(_make_entry(level="error", component="TopBar"))
        _ingest(_make_entry(level="error", component="TopBar"))
        _ingest(_make_entry(level="warn", component="Sidebar"))
        _ingest(_make_entry(level="info", component="App"))

        response = asyncio.get_event_loop().run_until_complete(prometheus_metrics())
        body = response.body.decode()

        assert "# HELP merid_ui_events_total" in body
        assert "# TYPE merid_ui_events_total counter" in body
        assert "merid_ui_events_total 4" in body
        assert "merid_ui_errors_total 2" in body
        assert "merid_ui_warnings_total 1" in body
        assert "merid_ui_info_total 1" in body
        assert "merid_ui_error_rate_per_sec" in body
        assert "merid_ui_buffer_size" in body
        assert 'merid_ui_component_errors_total{component="TopBar"} 2' in body

    def test_metrics_content_type(self):
        from web.api.telemetry import prometheus_metrics
        import asyncio
        response = asyncio.get_event_loop().run_until_complete(prometheus_metrics())
        assert "text/plain" in response.media_type
        assert "0.0.4" in response.media_type
