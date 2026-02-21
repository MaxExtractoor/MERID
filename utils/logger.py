from __future__ import annotations

import contextvars
import json
import logging
import os
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Optional

from merid_bootstrap import PROJECT_ROOT


# ── Correlation ID context ────────────────────────────────────────────
# Set per-request by the FastAPI correlation_id_middleware in web/main.py.
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

LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "full.log"

_LOGGER_CACHE: Dict[str, logging.Logger] = {}


class SafeRotatingFileHandler(RotatingFileHandler):
    """RotatingFileHandler that handles Windows file locking gracefully."""
    
    def doRollover(self):
        """Override to handle Windows file locking issues."""
        if self.stream:
            self.stream.close()
            self.stream = None
        
        if self.backupCount > 0:
            for i in range(self.backupCount - 1, 0, -1):
                sfn = self.rotation_filename("%s.%d" % (self.baseFilename, i))
                dfn = self.rotation_filename("%s.%d" % (self.baseFilename, i + 1))
                if os.path.exists(sfn):
                    try:
                        if os.path.exists(dfn):
                            os.remove(dfn)
                        os.rename(sfn, dfn)
                    except (OSError, PermissionError):
                        pass
            
            dfn = self.rotation_filename(self.baseFilename + ".1")
            try:
                if os.path.exists(dfn):
                    os.remove(dfn)
                self.rotate(self.baseFilename, dfn)
            except (OSError, PermissionError):
                pass
        
        if not self.delay:
            self.stream = self._open()


# ── Structured JSON formatter ─────────────────────────────────────────

class JsonFormatter(logging.Formatter):
    """Emit each log record as a single JSON line.

    Includes correlation_id from contextvars when available, making it
    possible to pivot from a frontend UI error → API request → DB query
    in a single log-aggregation query.
    """

    def format(self, record: logging.LogRecord) -> str:
        entry: Dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        cid = correlation_id_var.get()
        if cid:
            entry["correlation_id"] = cid

        if record.exc_info and record.exc_info[1]:
            entry["exception"] = self.formatException(record.exc_info)

        # Preserve any extra fields attached to the record
        for key in ("component", "endpoint", "duration_ms", "status_code"):
            val = getattr(record, key, None)
            if val is not None:
                entry[key] = val

        return json.dumps(entry, default=str)


# ── Human-readable console formatter (unchanged) ─────────────────────

_TEXT_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
_TEXT_DATEFMT = "%Y-%m-%d %H:%M:%S"

_json_logging_enabled = os.getenv("MERID_JSON_LOGS", "1").lower() in ("1", "true", "yes")


def get_logger(name: str) -> logging.Logger:
    """Return a module-level logger that writes to logs/full.log with UTF-8 encoding.

    File handler uses structured JSON format (includes correlation_id).
    Console handler uses human-readable text format for dev ergonomics.
    Set MERID_JSON_LOGS=0 to use text format for both handlers.
    """
    if name in _LOGGER_CACHE:
        return _LOGGER_CACHE[name]

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        text_formatter = logging.Formatter(_TEXT_FORMAT, _TEXT_DATEFMT)
        json_formatter = JsonFormatter()

        file_handler = SafeRotatingFileHandler(
            LOG_FILE, maxBytes=5_000_000, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(json_formatter if _json_logging_enabled else text_formatter)
        logger.addHandler(file_handler)

        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(text_formatter)
        logger.addHandler(stream_handler)

    _LOGGER_CACHE[name] = logger
    return logger

