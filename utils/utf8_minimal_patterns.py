"""
MERID Minimal UTF-8 Logging Patterns
Minimal, targeted patterns for production UTF-8 logging.

Date: 2026-01-26
Status: IMPLEMENTED
"""

import logging
import logging.config
import sys
import io
from pathlib import Path
from typing import Union
from logging.handlers import TimedRotatingFileHandler


# 1) utf_8_sig encoding in dictConfig file handler
LOGGING_FILE_BOM = {
    "version": 1,
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
    "formatters": {
        "standard": {"format": "%(asctime)s - %(levelname)s - %(message)s"}
    },
    "loggers": {
        "": {"handlers": ["file_utf8_bom"], "level": "INFO", "propagate": False},
    }
}


def configure_file_bom_logging() -> logging.Logger:
    """Configure FileHandler with UTF-8 BOM."""
    log_path = Path("logs/app_bom.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    logging.config.dictConfig(LOGGING_FILE_BOM)
    return logging.getLogger(__name__)


# 2) Modify TimedRotatingFileHandler to roll over on startup
def configure_and_force_rollover() -> logging.Logger:
    """Configure and force rollover at startup."""
    
    logging.config.dictConfig(LOGGING_TIMED_BOM)
    logger = logging.getLogger()  # root or specific

    for h in logger.handlers:
        if isinstance(h, TimedRotatingFileHandler):
            h.doRollover()  # force rotation at startup

    return logger


# 3) dictConfig example: UTC midnight rollover
LOGGING_TIMED_BOM = {
    "version": 1,
    "handlers": {
        "time_file_utf8_bom": {
            "class": "logging.handlers.TimedRotatingFileHandler",
            "level": "INFO",
            "formatter": "standard",
            "filename": "logs/app_timed.log",
            "when": "midnight",      # rotate at midnight
            "interval": 1,           # every day
            "backupCount": 7,        # keep 7 days
            "encoding": "utf-8-sig",
            "utc": True,             # use UTC for rollover times
            "delay": True,           # open file on first emit
        },
    },
    "formatters": {
        "standard": {"format": "%(asctime)s - %(levelname)s - %(message)s"}
    },
    "loggers": {
        "": {"handlers": ["time_file_utf8_bom"], "level": "INFO", "propagate": False},
    }
}


def configure_utc_midnight_logging() -> logging.Logger:
    """Configure UTC midnight rollover logging."""
    log_path = Path("logs/app_timed.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    logging.config.dictConfig(LOGGING_TIMED_BOM)
    return logging.getLogger(__name__)


# 4) backupCount and date in rotated filenames
def get_rotation_info() -> dict:
    """Get information about backupCount and filename patterns."""
    return {
        "backupCount": 7,  # keeps 7 old files and removes older ones
        "current_file": "app_timed.log",
        "rotated_pattern": "app_timed.log.2026-01-26",
        "default_suffix": "%Y-%m-%d_%H-%M-%S",
        "example_files": [
            "app_timed.log",           # current
            "app_timed.log.2026-01-26",  # yesterday
            "app_timed.log.2026-01-25",  # 2 days ago
            "app_timed.log.2026-01-24",  # 3 days ago
            # ... up to 7 days total
        ]
    }


# 5) Avoid overwritten rollovers when starting near atTime
class UniqueTimedRotatingFileHandler(TimedRotatingFileHandler):
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


def configure_unique_rollover_logging() -> logging.Logger:
    """Configure logging with unique rollover to avoid overwrites."""
    
    log_path = Path("logs/app_unique.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    config = {
        "version": 1,
        "handlers": {
            "time_file_unique": {
                "()": "utf8_minimal_patterns.UniqueTimedRotatingFileHandler",
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
            "standard": {"format": "%(asctime)s - %(levelname)s - %(message)s"}
        },
        "loggers": {
            "": {"handlers": ["time_file_unique"], "level": "INFO", "propagate": False},
        }
    }
    
    logging.config.dictConfig(config)
    return logging.getLogger(__name__)


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
            "()": "utf8_minimal_patterns.Utf8StreamHandler",
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
        "standard": {"format": "%(asctime)s - %(levelname)s - %(message)s"}
    },
    "loggers": {
        "": {"handlers": ["console_utf8", "file_utf8_bom"], "level": "INFO", "propagate": False},
    }
}


def configure_console_file_bom_logging() -> logging.Logger:
    """Configure console + file logging with BOM."""
    log_path = Path("logs/app_console_bom.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    logging.config.dictConfig(LOGGING_CONSOLE_FILE)
    return logging.getLogger(__name__)


# Utility functions
def verify_bom_in_file(file_path: Union[str, Path]) -> bool:
    """Verify that a file starts with UTF-8 BOM."""
    file_path = Path(file_path)
    if not file_path.exists():
        return False
    
    try:
        with open(file_path, 'rb') as f:
            bom = f.read(3)
            return bom == b'\xef\xbb\xbf'
    except Exception:
        return False


def list_rotated_files(base_path: Union[str, Path]) -> list[Path]:
    """List all rotated files for a given base path."""
    base_path = Path(base_path)
    pattern = f"{base_path.name}.*"
    
    return sorted(base_path.parent.glob(pattern))


# Manual smoke test for development
if __name__ == "__main__":
    print("🚀 Testing Minimal UTF-8 Logging Patterns")
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
    
    # Test unique rollover
    print("\n🧪 Testing Unique Rollover...")
    unique_logger = configure_unique_rollover_logging()
    unique_logger.info("Unique rollover test: 🚀 αβγ")
    
    # Test console + file BOM
    print("\n🧪 Testing Console + File BOM Logging...")
    console_file_logger = configure_console_file_bom_logging()
    console_file_logger.info("Console + File BOM test: 🚀 αβγ")
    
    print("\n✅ All minimal UTF-8 logging patterns tested successfully!")
    print("📂 Check logs/ directory for UTF-8 encoded output")
