from __future__ import annotations

import contextvars
import glob
import json
import logging
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Optional

from merid_bootstrap import PROJECT_ROOT
from config.monitoring_config import get_monitoring_config, LoggingConfig

# Import secrets manager for log sanitization
try:
    from utils.secrets_manager import is_sensitive_field, mask_sensitive_string, sanitize_dict_for_logging
    SECRETS_MANAGER_AVAILABLE = True
except ImportError:
    SECRETS_MANAGER_AVAILABLE = False


# ── Asset-Aware Price Formatting ───────────────────────────────────────
# Different crypto assets have different price ranges and need appropriate
# decimal precision for logging and display.

def format_price(asset: str, price: float) -> str:
    """Format price with appropriate decimal places based on asset.
    
    Args:
        asset: Asset symbol (e.g., "BTC", "ETH", "SOL", "XRP", "DOGE")
        price: Price value to format
    
    Returns:
        Formatted price string with appropriate decimal places
    """
    # Define decimal places for each asset based on typical price range
    # BTC: ~$60,000 -> 2 decimal places
    # ETH: ~$1,700 -> 2 decimal places
    # SOL: ~$77 -> 4 decimal places
    # XRP: ~$1.08 -> 4 decimal places
    # DOGE: ~$0.07 -> 7 decimal places
    asset_precision = {
        "BTC": 2,
        "ETH": 2,
        "SOL": 4,
        "XRP": 4,
        "DOGE": 7
    }
    
    precision = asset_precision.get(asset.upper(), 4)  # Default to 4 decimals
    return f"{price:.{precision}f}"


# ── Correlation ID context ────────────────────────────────────────────
# set per-request by the FastAPI correlation_id_middleware in web/main.py.
# Any log line emitted during that request will include the correlation ID.

correlation_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "correlation_id", default=None
)


def get_correlation_id() -> Optional[str]:
    """Return the current request's correlation ID, or None."""
    return correlation_id_var.get()


def set_correlation_id(cid: str) -> contextvars.Token:
    """Set the correlation ID for the current async context."""
    return correlation_id_var.set(cid)


# ── BUG-8: Task context ContextVars ───────────────────────────────────
# These are set at the top of each MeridLoop tick and propagated through
# agent/venue coroutines so every background-task log line carries the
# same structured dimensions that the HTTP correlation_id provides for
# request-path logs.

_task_venue_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "task_venue", default=None
)
_task_agent_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "task_agent_id", default=None
)
_task_mode_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "task_mode", default=None
)
_task_env_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "task_env", default=None
)
_task_tick_var: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar(
    "task_tick", default=None
)


def set_task_context(
    *,
    venue: Optional[str] = None,
    agent_id: Optional[str] = None,
    mode: Optional[str] = None,
    env: Optional[str] = None,
    tick: Optional[int] = None,
    correlation_id: Optional[str] = None,
) -> None:
    """Set structured log context for background tasks (loop ticks, agent cycles).

    Call once at the start of a MeridLoop.tick() or agent cycle so that all
    log lines emitted during that context carry the same dimensions:

        venue, agent_id, mode (paper/live), env (demo/production), tick

    Unlike set_correlation_id() which returns a Token for reset, this
    function is fire-and-set — context is propagated within the current
    asyncio Task (contextvars are task-local by design).
    """
    if venue is not None:
        _task_venue_var.set(venue)
    if agent_id is not None:
        _task_agent_id_var.set(agent_id)
    if mode is not None:
        _task_mode_var.set(mode)
    if env is not None:
        _task_env_var.set(env)
    if tick is not None:
        _task_tick_var.set(tick)
    if correlation_id is not None:
        correlation_id_var.set(correlation_id)  # also propagates to HTTP-style CID field

LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "full.log"
# Production-visible log file in project root for easy access
PRODUCTION_LOG_FILE = PROJECT_ROOT / "server_output.log"

_LOGGER_CACHE: Dict[str, logging.Logger] = {}


def _archive_suffix() -> str:
    """Return a UTC timestamp suffix safe for Windows filenames."""
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def _safe_warning(message: str) -> None:
    """Emit a rotation warning without using the logging system (avoid recursion)."""
    try:
        sys.stderr.write(f"[SafeRotatingFileHandler] {message}\n")
    except Exception:
        pass


class SafeRotatingFileHandler(RotatingFileHandler):
    """RotatingFileHandler that handles Windows file locking gracefully.

    Problem it solves: on Windows multiple file handles (from multiple logger
    instances) can keep a log file open, which prevents ``os.rename`` and causes
    standard ``RotatingFileHandler.doRollover`` to fail with ``PermissionError``.
    Once rotation fails, the handler falls back to appending to the same file,
    which grows unbounded (observed at 6.8 GB).

    ``utils.logger.get_logger`` now uses *shared* handler instances so only one
    stream per log file exists. This handler also uses ``os.replace`` (atomic on
    Windows when the file is not locked) and, if that still fails, falls back to
    a timestamped archive so the current file can be reset instead of growing
    forever.
    """

    def _open(self):
        """Open the log file, creating parent directories if necessary."""
        path = Path(self.baseFilename)
        path.parent.mkdir(parents=True, exist_ok=True)
        return super()._open()

    def doRollover(self):
        """Override to handle Windows file locking issues.

        2026-08-11: Prefer an in-place copy-truncate when ``os.replace`` would
        fail because another process (e.g. a PowerShell ``Start-Transcript``
        wrapping the server start) holds the log file open.  ``os.replace``
        requires that the source not be in use, but a copy+truncate only
        requires read/write sharing, which ``Start-Transcript`` normally grants.
        """
        if self.backupCount > 0 and self.stream:
            # Shift existing backups: N -> N+1, N-1 -> N, etc.
            for i in range(self.backupCount - 1, 0, -1):
                sfn = self.rotation_filename("%s.%d" % (self.baseFilename, i))
                dfn = self.rotation_filename("%s.%d" % (self.baseFilename, i + 1))
                if os.path.exists(sfn):
                    try:
                        os.replace(sfn, dfn)
                    except (OSError, PermissionError) as exc:
                        _safe_warning(
                            f"Failed to shift backup {sfn} -> {dfn}: {exc}"
                        )

            dfn = self.rotation_filename(self.baseFilename + ".1")
            if os.path.exists(dfn):
                try:
                    os.remove(dfn)
                except (OSError, PermissionError) as exc:
                    _safe_warning(f"Failed to remove old backup {dfn}: {exc}")

            # 2026-08-11: try copy-truncate while keeping the stream open.
            # Open a separate read handle because the main stream may be append-only.
            # This avoids renaming a file held by an external tail/transcript.
            try:
                self.stream.flush()
                with open(self.baseFilename, "r", encoding=self.encoding or "utf-8") as src:
                    with open(dfn, "w", encoding=self.encoding or "utf-8") as backup:
                        shutil.copyfileobj(src, backup)
                self.stream.seek(0)
                self.stream.truncate(0)
                self.stream.seek(0)
                return
            except (OSError, PermissionError, ValueError) as exc:
                _safe_warning(
                    f"Copy-truncate rollover failed for {self.baseFilename}: {exc}; "
                    f"falling back to rename/archive"
                )

        # Legacy fallback: close the stream and try to rename/archive.
        if self.stream:
            try:
                self.stream.close()
            except Exception:
                pass
            self.stream = None

        if self.backupCount > 0:
            # Shift existing backups again in case copy-truncate did not run.
            for i in range(self.backupCount - 1, 0, -1):
                sfn = self.rotation_filename("%s.%d" % (self.baseFilename, i))
                dfn = self.rotation_filename("%s.%d" % (self.baseFilename, i + 1))
                if os.path.exists(sfn):
                    try:
                        os.replace(sfn, dfn)
                    except (OSError, PermissionError) as exc:
                        _safe_warning(
                            f"Failed to shift backup {sfn} -> {dfn}: {exc}"
                        )

            dfn = self.rotation_filename(self.baseFilename + ".1")
            if os.path.exists(dfn):
                try:
                    os.remove(dfn)
                except (OSError, PermissionError) as exc:
                    _safe_warning(f"Failed to remove old backup {dfn}: {exc}")

            try:
                self.rotate(self.baseFilename, dfn)
            except (OSError, PermissionError) as exc:
                _safe_warning(
                    f"Failed to rotate {self.baseFilename} -> {dfn}: {exc}"
                )
                archive = self.rotation_filename(
                    f"{self.baseFilename}.rotated.{_archive_suffix()}"
                )
                try:
                    os.replace(self.baseFilename, archive)
                except (OSError, PermissionError) as exc2:
                    _safe_warning(
                        f"Could not archive {self.baseFilename} to {archive}: {exc2}"
                    )

        if not self.delay:
            self.stream = self._open()


# ── Shared file handlers ──────────────────────────────────────────────
# Multiple loggers must write to the same files, but each logger having its own
# RotatingFileHandler keeps a separate Windows file handle open. That prevents
# the handler from renaming the file when it is time to rotate. We therefore
# create one handler per file and share it across all loggers.

_file_handler: Optional[SafeRotatingFileHandler] = None
_production_handler: Optional[SafeRotatingFileHandler] = None
_stream_handler: Optional[logging.StreamHandler] = None
_handlers_initialized: bool = False


def _ensure_handlers() -> None:
    """Create the shared file + console handlers (idempotent) with configuration-based settings."""
    global _file_handler, _production_handler, _stream_handler, _handlers_initialized
    if _handlers_initialized:
        return

    # Load logging configuration
    log_config = get_monitoring_config().logging

    text_formatter = logging.Formatter(_TEXT_FORMAT, _TEXT_DATEFMT)
    json_formatter = JsonFormatter(
        include_timestamp=log_config.include_timestamp,
        include_level=log_config.include_level,
        include_logger=log_config.include_logger,
        include_correlation_id=log_config.include_correlation_id,
        include_stack_trace=log_config.include_stack_trace,
    )

    # SECURITY: Add sensitive data filter to all handlers
    sensitive_filter = SensitiveDataFilter(
        enabled=log_config.filter_sensitive_data,
        sensitive_fields=log_config.sensitive_fields
    )

    # Calculate max bytes from config (MB to bytes)
    max_file_size_bytes = log_config.max_file_size_mb * 1_000_000

    _file_handler = SafeRotatingFileHandler(
        LOG_FILE, maxBytes=max_file_size_bytes, backupCount=log_config.backup_count, encoding="utf-8"
    )
    _file_handler.setFormatter(json_formatter if log_config.format == "json" else text_formatter)
    _file_handler.addFilter(sensitive_filter)
    _file_handler.setLevel(getattr(logging, log_config.level.upper(), logging.INFO))

    _production_handler = SafeRotatingFileHandler(
        PRODUCTION_LOG_FILE, maxBytes=max_file_size_bytes, backupCount=log_config.backup_count, encoding="utf-8"
    )
    _production_handler.setFormatter(text_formatter)
    _production_handler.addFilter(sensitive_filter)

    _stream_handler = logging.StreamHandler()
    _stream_handler.setFormatter(text_formatter)
    _stream_handler.addFilter(sensitive_filter)

    _handlers_initialized = True


def startup_log_cleanup() -> None:
    """Archive oversized log files before any handler opens them.

    Call this once at process startup, before the first ``get_logger()`` call.
    It renames existing log files that exceed their configured ``maxBytes``
    threshold so the process starts with small, fresh logs. Old archives are
    preserved with a UTC timestamp suffix and can be removed manually.
    """
    log_config = get_monitoring_config().logging
    max_file_size_bytes = log_config.max_file_size_mb * 1_000_000
    
    for path, label in (
        (LOG_FILE, "full.log"),
        (PRODUCTION_LOG_FILE, "server_output.log"),
    ):
        try:
            if path.exists() and path.stat().st_size > max_file_size_bytes:
                archive = path.parent / f"{path.name}.startup.{_archive_suffix()}"
                _safe_warning(
                    f"Archiving oversized {label} ({path.stat().st_size / 1_000_000:.1f} MB) -> {archive}"
                )
                # ``os.replace`` works even if the file is open as long as we are
                # the only writer. Other processes reading the file will simply see
                # the old path disappear. Creating a new empty file afterward lets
                # the logger open a fresh stream on the same path.
                os.replace(str(path), str(archive))
                # Ensure a fresh empty file exists for the logger.
                path.touch(exist_ok=True)
        except (OSError, PermissionError) as exc:
            _safe_warning(f"Could not archive {label} at startup: {exc}")


def cleanup_old_logs() -> None:
    """Clean up log files older than the configured retention period.
    
    This function should be called periodically (e.g., daily) to remove
    old log files and archives that exceed the retention policy.
    
    Uses the retention_days from LoggingConfig to determine which files to delete.
    """
    log_config = get_monitoring_config().logging
    retention_days = log_config.retention_days
    cutoff_time = time.time() - (retention_days * 86400)  # Convert days to seconds
    
    log_dir = Path(log_config.log_dir)
    if not log_dir.exists():
        return
    
    try:
        deleted_count = 0
        for log_file in log_dir.glob("*.log*"):
            try:
                file_mtime = log_file.stat().st_mtime
                if file_mtime < cutoff_time:
                    log_file.unlink()
                    deleted_count += 1
                    _safe_warning(f"Deleted old log file: {log_file}")
            except (OSError, PermissionError) as exc:
                _safe_warning(f"Could not delete old log file {log_file}: {exc}")
        
        if deleted_count > 0:
            _safe_warning(f"Log cleanup completed: deleted {deleted_count} files older than {retention_days} days")
    except Exception as exc:
        _safe_warning(f"Log cleanup failed: {exc}")


# ── Structured JSON formatter ─────────────────────────────────────────

class JsonFormatter(logging.Formatter):
    """Emit each log record as a single JSON line with configurable fields.

    Includes correlation_id from contextvars when available, making it
    possible to pivot from a frontend UI error → API request → DB query
    in a single log-aggregation query.
    
    SECURITY: Automatically masks sensitive data in log messages and extra fields.
    
    Args:
        include_timestamp: Include timestamp in log output
        include_level: Include log level in log output
        include_logger: Include logger name in log output
        include_correlation_id: Include correlation ID in log output
        include_stack_trace: Include stack trace for errors
    """

    def __init__(
        self,
        include_timestamp: bool = True,
        include_level: bool = True,
        include_logger: bool = True,
        include_correlation_id: bool = True,
        include_stack_trace: bool = True,
    ):
        super().__init__()
        self.include_timestamp = include_timestamp
        self.include_level = include_level
        self.include_logger = include_logger
        self.include_correlation_id = include_correlation_id
        self.include_stack_trace = include_stack_trace

    def _sanitize_value(self, key: str, value: Any) -> Any:
        """Sanitize a value based on its key name.
        
        Args:
            key: The field name
            value: The value to sanitize
            
        Returns:
            Sanitized value (masked if sensitive)
        """
        if SECRETS_MANAGER_AVAILABLE and is_sensitive_field(key):
            return mask_sensitive_string(str(value) if value else "")
        return value

    def format(self, record: logging.LogRecord) -> str:
        entry: Dict[str, Any] = {}

        # Add timestamp if configured
        if self.include_timestamp:
            entry["ts"] = datetime.now(timezone.utc).isoformat()

        # Add level if configured
        if self.include_level:
            entry["level"] = record.levelname

        # Add logger name if configured
        if self.include_logger:
            entry["logger"] = record.name

        # Always include message
        entry["message"] = record.getMessage()

        # Add correlation ID if configured and available
        if self.include_correlation_id:
            cid = correlation_id_var.get()
            if cid:
                entry["correlation_id"] = cid

        # Add exception if configured and available
        if self.include_stack_trace and record.exc_info and record.exc_info[1]:
            entry["exception"] = self.formatException(record.exc_info)

        # BUG-8: structured trading dimensions from ContextVars (set by loop/agents)
        _venue = _task_venue_var.get()
        if _venue:
            entry["venue"] = _venue
        _agent = _task_agent_id_var.get()
        if _agent:
            entry["agent_id"] = _agent
        _mode = _task_mode_var.get()
        if _mode:
            entry["mode"] = _mode
        _env = _task_env_var.get()
        if _env:
            entry["env"] = _env
        _tick = _task_tick_var.get()
        if _tick is not None:
            entry["tick"] = _tick

        # Preserve any extra fields attached to the record
        # SECURITY: Sanitize sensitive fields
        for key in ("component", "endpoint", "duration_ms", "status_code",
                    "venue", "agent_id", "mode", "market_id", "strategy",
                    "password", "token", "api_key", "secret", "credential"):
            val = getattr(record, key, None)
            if val is not None:
                entry.setdefault(key, self._sanitize_value(key, val))

        # SECURITY: Sanitize any other extra fields that might be sensitive
        if SECRETS_MANAGER_AVAILABLE:
            for key, val in record.__dict__.items():
                if key not in entry and not key.startswith('_') and key not in (
                    'name', 'msg', 'args', 'created', 'filename', 'funcName',
                    'levelname', 'levelno', 'lineno', 'module', 'msecs',
                    'message', 'pathname', 'process', 'processName',
                    'relativeCreated', 'thread', 'threadName', 'exc_info',
                    'exc_text', 'stack_info', 'getMessage'
                ):
                    entry[key] = self._sanitize_value(key, val)

        return json.dumps(entry, default=str)


# ── Log Sanitization Filter ─────────────────────────────────────────────

class SensitiveDataFilter(logging.Filter):
    """Filter that masks sensitive data in log messages with configurable fields.
    
    This filter scans log messages for patterns that look like sensitive data
    (API keys, tokens, passwords) and masks them before logging.
    
    Args:
        enabled: Whether sensitive data filtering is enabled
        sensitive_fields: List of field names to consider sensitive
    """
    
    # CRITICAL FIX (2026-08-27): Removed blanket hex/base64 regexes that
    # over-redacted fill_id, order_id, client_order_id and other correlation
    # identifiers. Redaction is now keyed on explicit field/value prefixes.
    #
    # The compiled pattern includes the caller-supplied ``sensitive_fields``
    # (e.g. custom_secret, custom_token) plus the canonical secret prefixes.
    # This preserves the field name as a queryable token while replacing the
    # secret payload with [REDACTED].
    _BASE_SECRET_PREFIXES = (
        "password", "secret", "token", "bearer", "api_key", "private_key",
        "access_key", "secret_key", "session_id", "credential", "auth",
    )

    def __init__(self, enabled: bool = True, sensitive_fields: Optional[List[str]] = None):
        super().__init__()
        self.enabled = enabled
        self.sensitive_fields = set(sensitive_fields or [
            "api_key", "secret", "password", "token", "private_key",
            "credential", "auth", "bearer", "session_id"
        ])

        import re
        terms = sorted(
            set(self.sensitive_fields) | set(self._BASE_SECRET_PREFIXES),
            key=len,
            reverse=True,
        )
        field_pattern = "|".join(re.escape(term) for term in terms)
        # Match ``field_name = value`` or ``field_name: value`` with word
        # boundaries so ``custom_secret`` matches but ``secret`` inside
        # ``tokenized_secret_handling`` does not.
        pattern = re.compile(
            rf'\b({field_pattern})\b["\s]*[:=]["\s]*[^\s,}}]+',
            re.IGNORECASE,
        )
        self._compiled_patterns = [(pattern, r'\1=[REDACTED]')]
    
    def filter(self, record: logging.LogRecord) -> bool:
        """Filter and sanitize log record.
        
        Args:
            record: The log record to filter
            
        Returns:
            True (always allow the record)
        """
        if not self.enabled:
            return True
        
        # Sanitize the message
        for pattern, replacement in self._compiled_patterns:
            record.msg = pattern.sub(replacement, str(record.msg))
        
        # Sanitize args if present
        if record.args:
            sanitized_args = []
            for arg in record.args:
                if isinstance(arg, str):
                    for pattern, replacement in self._compiled_patterns:
                        arg = pattern.sub(replacement, arg)
                    sanitized_args.append(arg)
                else:
                    sanitized_args.append(arg)
            record.args = tuple(sanitized_args)
        
        return True


# ── Human-readable console formatter (unchanged) ─────────────────────

_TEXT_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
_TEXT_DATEFMT = "%Y-%m-%d %H:%M:%S"

# ── Hot-path data-plane log throttling ────────────────────────────────
# These loggers emit several INFO lines for EVERY WebSocket orderbook
# message (~250 msg/s across the 5 crypto markets). Left at INFO they:
#   * write thousands of lines/sec to logs/full.log (grows to multi-GB),
#   * peg the CPU at ~100% and cause 400ms+ "Slow WS callback" stalls,
#   * trigger bridge queue overflow ("dropped 2000 events") that starves
#     the trading loop of fresh market data.
# Throttle them to WARNING by default so real signals/orders remain
# visible while keeping the data-plane hot path fast.

_VERBOSE_DATAPLANE = os.getenv("MERID_VERBOSE_DATAPLANE", "false").lower() in ("1", "true", "yes")
_NOISY_DATAPLANE_LOGGERS = (
    "merid.event_venues.kalshi.ws_bridge",
    "merid.event_venues.kalshi.ws_bridge_client",
    "kalshi.ws_bridge",
    "kalshi.ws_client",
    "merid.event_venues.kalshi.market_state",
    "merid.event_venues.kalshi.market_state_store",
    "merid.event_venues.kalshi.orderbook",
)


def get_logger(name: str) -> logging.Logger:
    """Return a module-level logger that writes to logs/full.log with UTF-8 encoding.

    File handler uses structured JSON format (includes correlation_id).
    Console handler uses human-readable text format for dev ergonomics.
    Log levels and format are configurable via LoggingConfig.
    """
    if name in _LOGGER_CACHE:
        return _LOGGER_CACHE[name]

    logger = logging.getLogger(name)
    
    # Load logging configuration
    log_config = get_monitoring_config().logging
    
    # Determine log level from configuration
    # Check component-specific levels first
    component_level = None
    for component, level in log_config.component_levels.items():
        if component in name:
            component_level = level
            break
    
    if component_level:
        logger.setLevel(getattr(logging, component_level.upper(), logging.INFO))
    else:
        logger.setLevel(getattr(logging, log_config.level.upper(), logging.INFO))
    
    # Throttle ultra-noisy WS/market-state data-plane loggers to WARNING to keep
    # the event loop responsive and the trading loop fed (see note above).
    if name in _NOISY_DATAPLANE_LOGGERS and not _VERBOSE_DATAPLANE:
        logger.setLevel(logging.WARNING)
    
    # Propagate to root so pytest caplog can capture assertions during test runs.
    # Production has no root handlers, so this does not cause duplicate output.
    logger.propagate = True

    _ensure_handlers()

    if _file_handler not in logger.handlers:
        logger.addHandler(_file_handler)
    if _production_handler not in logger.handlers:
        logger.addHandler(_production_handler)
    if _stream_handler not in logger.handlers:
        logger.addHandler(_stream_handler)

    _LOGGER_CACHE[name] = logger
    return logger


# Backward-compatible aliases for existing code
getLogger = get_logger
