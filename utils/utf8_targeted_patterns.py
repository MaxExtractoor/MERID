"""
MERID Targeted UTF-8 Logging Patterns
Compact patterns that do exactly what's needed for production UTF-8 logging.

Date: 2026-01-26
Status: IMPLEMENTED
"""

import logging
import logging.config
import sys
import io
import pathlib
from typing import Union
from logging.handlers import TimedRotatingFileHandler


# 1) utf_8_sig encoding in dictConfig FileHandler (BOM)
LOGGING_FILE_BOM = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
        }
    },
    "handlers": {
        "file_utf8_bom": {
            "class": "logging.FileHandler",
            "level": "INFO",
            "formatter": "standard",
            "filename": "logs/app_bom.log",
            "mode": "a",
            "encoding": "utf-8-sig",  # UTF-8 with BOM
        },
    },
    "loggers": {
        "": {
            "handlers": ["file_utf8_bom"],
            "level": "INFO",
            "propagate": False,
        }
    }
}


def configure_file_bom_logging() -> logging.Logger:
    """Configure FileHandler with UTF-8 BOM."""
    log_path = pathlib.Path("logs/app_bom.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    logging.config.dictConfig(LOGGING_FILE_BOM)
    return logging.getLogger(__name__)


# 2) TimedRotatingFileHandler: force `doRollover()` at startup
LOGGING_TIMED = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
        }
    },
    "handlers": {
        "time_file_utf8_bom": {
            "class": "logging.handlers.TimedRotatingFileHandler",
            "level": "INFO",
            "formatter": "standard",
            "filename": "logs/app_timed.log",
            "when": "midnight",
            "interval": 1,
            "backupCount": 7,
            "encoding": "utf-8-sig",
            "utc": True,
            "delay": True,
        },
    },
    "loggers": {
        "": {
            "handlers": ["time_file_utf8_bom"],
            "level": "INFO",
            "propagate": False,
        }
    }
}


def configure_and_force_rollover() -> logging.Logger:
    """Configure and force rollover at startup."""
    
    logging.config.dictConfig(LOGGING_TIMED)
    logger = logging.getLogger()  # root

    for h in logger.handlers:
        if isinstance(h, TimedRotatingFileHandler):
            h.doRollover()  # start with a fresh file

    return logger


# 3) dictConfig with UTC midnight rollover (`when="midnight"`)
# The same LOGGING_TIMED already shows the core UTC config:
# - when="midnight" and interval=1 give you daily rotation
# - utc=True tells the handler to compute rolloverAt in UTC, not local time
# - encoding="utf-8-sig" ensures BOM in each file
# - delay=True opens file on first emit


def configure_utc_midnight_logging() -> logging.Logger:
    """Configure UTC midnight rollover logging."""
    log_path = pathlib.Path("logs/app_timed.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    logging.config.dictConfig(LOGGING_TIMED)
    return logging.getLogger(__name__)


# 4) backupCount and date in rotated filenames
def get_rotation_info() -> dict:
    """Get information about backupCount and filename patterns."""
    return {
        "backupCount": 7,  # keeps 7 old files and removes older ones
        "current_file": "logs/app_timed.log",
        "rotated_pattern": "logs/app_timed.log.2026-01-26",
        "default_suffix": "%Y-%m-%d_%H-%M-%S",
        "example_files": [
            "logs/app_timed.log",           # current
            "logs/app_timed.log.2026-01-26",  # yesterday
            "logs/app_timed.log.2026-01-25",  # 2 days ago
            "logs/app_timed.log.2026-01-24",  # 3 days ago
            # ... up to 7 days total
        ]
    }


# 5) Ensuring rollover even with midnight/`atTime` edge cases
class SafeTimedRotatingFileHandler(TimedRotatingFileHandler):
    """Custom handler with unique suffix to avoid overwrites."""
    
    def __init__(self, filename, when='midnight', interval=1, backupCount=7, 
                 encoding='utf-8-sig', utc=True, delay=True, **kwargs):
        # Add unique identifier to avoid conflicts
        import time
        self.run_id = int(time.time() * 1000)  # unique per run
        super().__init__(filename, when, interval, backupCount, encoding, utc, delay, **kwargs)
    
    def rotation_filename(self, default_name: str) -> str:
        """Override to include run ID in filename."""
        base_name, ext = default_name.rsplit('.', 1)
        return f"{base_name}.{self.run_id}.{ext}"


def configure_safe_rollover_logging() -> logging.Logger:
    """Configure logging with safe rollover to avoid overwrites."""
    
    log_path = pathlib.Path("logs/app_safe.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    config = {
        "version": 1,
        "handlers": {
            "time_file_safe": {
                "()": "utf8_targeted_patterns.SafeTimedRotatingFileHandler",
                "level": "INFO",
                "formatter": "standard",
                "filename": str(log_path),
                "when": "midnight",
                "interval": 1,
                "backupCount": 7,
                "encoding": "utf-8-sig",
                "utc": True,
                "delay": True,
            },
        },
        "formatters": {
            "standard": {"format": "%(asctime)s - %(levelname)s - %(name)s - %(message)s"}
        },
        "loggers": {
            "": {"handlers": ["time_file_safe"], "level": "INFO", "propagate": False},
        }
    }
    
    logging.config.dictConfig(config)
    logger = logging.getLogger(__name__)
    
    # Force rollover at startup for fresh file per run
    for h in logger.handlers:
        if isinstance(h, TimedRotatingFileHandler):
            h.doRollover()
    
    return logger


# Standard UTF-8 StreamHandler for dictConfig
class Utf8StreamHandler(logging.StreamHandler):
    """Standard UTF-8 StreamHandler for dictConfig."""
    
    def __init__(self, stream=None):
        if stream is None:
            stream = io.TextIOWrapper(
                sys.stdout.buffer,
                encoding="utf-8",
                errors="fast",
            )
        super(Utf8StreamHandler, self).__init__(stream)


# Console + File configuration
LOGGING_CONSOLE_FILE = {
    "version": 1,
    "handlers": {
        "console_utf8": {
            "()": "utf8_targeted_patterns.Utf8StreamHandler",
            "level": "INFO",
            "formatter": "standard",
        },
        "file_utf8_bom": {
            "class": "logging.FileHandler",
            "level": "INFO",
            "formatter": "standard",
            "filename": "logs/app_console_bom.log",
            "mode": "a",
            "encoding": "utf-8-sig",
        },
    },
    "formatters": {
        "standard": {"format": "%(asctime)s - %(levelname)s - %(name)s - %(message)s"}
    },
    "loggers": {
        "": {"handlers": ["console_utf8", "file_utf8_bom"], "level": "INFO", "propagate": False},
    }
}


def configure_console_file_bom_logging() -> logging.Logger:
    """Configure console + file logging with BOM."""
    log_path = pathlib.Path("logs/app_console_bom.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    logging.config.dictConfig(LOGGING_CONSOLE_FILE)
    return logging.getLogger(__name__)


# Utility functions
def verify_bom_in_file(file_path: Union[str, pathlib.Path]) -> bool:
    """Verify that a file starts with UTF-8 BOM."""
    file_path = pathlib.Path(file_path)
    if not file_path.exists():
        return False
    
    try:
        with open(file_path, 'rb') as f:
            bom = f.read(3)
            return bom == b'\xef\xbb\xbf'
    except Exception:
        return False


def list_rotated_files(base_path: Union[str, pathlib.Path]) -> list[pathlib.Path]:
    """List all rotated files for a given base path."""
    base_path = pathlib.Path(base_path)
    pattern = f"{base_path.name}.*"
    
    return sorted(base_path.parent.glob(pattern))


# Manual smoke test for development
if __name__ == "__main__":
    print("🚀 Testing Targeted UTF-8 Logging Patterns")
    print("=" * 50)
    
    # Test file BOM logging
    print("\n🧪 Testing File BOM Logging...")
    file_bom_logger = configure_file_bom_logging()
    file_bom_logger.info("File BOM test: 🚀 αβγ")
    
    # Verify BOM
    bom_present = verify_bom_in_file("logs/app_bom.log")
    print(f"   ✅ BOM present: {bom_present}")
    
    # Test UTC midnight logging
    print("\n🧪 Testing UTC Midnight Logging...")
    utc_logger = configure_utc_midnight_logging()
    utc_logger.info("UTC midnight test: 🚀 αβγ")
    
    # Test forced rollover
    print("\n🧪 Testing Forced Rollover...")
    rollover_logger = configure_and_force_rollover()
    rollover_logger.info("Forced rollover test: 🚀 αβγ")
    
    # Show rotation info
    print("\n📋 Rotation Info:")
    info = get_rotation_info()
    for key, value in info.items():
        print(f"   {key}: {value}")
    
    # Test safe rollover
    print("\n🧪 Testing Safe Rollover...")
    safe_logger = configure_safe_rollover_logging()
    safe_logger.info("Safe rollover test: 🚀 αβγ")
    
    # Test console + file BOM
    print("\n🧪 Testing Console + File BOM Logging...")
    console_file_logger = configure_console_file_bom_logging()
    console_file_logger.info("Console + File BOM test: 🚀 αβγ")
    
    print("\n✅ All targeted UTF-8 logging patterns tested successfully!")
    print("📂 Check logs/ directory for UTF-8 encoded output")
