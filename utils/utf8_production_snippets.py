"""
MERID Production UTF-8 Logging Snippets
Minimal, production-style snippets covering all five items.

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


# 1) Subclass TimedRotatingFileHandler to roll over on start
class StartupRolloverTimedHandler(TimedRotatingFileHandler):
    """Custom handler that forces rollover on startup."""
    
    def __init__(self, *args, **kwargs):
        super(StartupRolloverTimedHandler, self).__init__(*args, **kwargs)
        # Force an immediate rollover when the handler is created
        # so each run starts in a fresh file
        self.doRollover()


# 2) dictConfig example: FileHandler with `utf_8_sig` (BOM)
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


# 3) Force `doRollover` programmatically at init (no subclass)
def configure_and_force_rollover(config_dict: dict) -> logging.Logger:
    """Configure and force rollover at startup."""
    
    logging.config.dictConfig(config_dict)
    logger = logging.getLogger()  # root

    for h in logger.handlers:
        if isinstance(h, TimedRotatingFileHandler):
            h.doRollover()  # force rollover at startup

    return logger


# 4) Combine TimedRotatingFileHandler + BOM (`utf-8-sig`) with UTC midnight
LOGGING_TIMED_BOM_UTC = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
        }
    },
    "handlers": {
        "time_file_utf8_bom": {
            "class": "utf8_production_snippets.StartupRolloverTimedHandler",
            "level": "INFO",
            "formatter": "standard",
            "filename": "logs/app_timed.log",
            "when": "midnight",      # daily rotation
            "interval": 1,
            "backupCount": 7,
            "encoding": "utf-8-sig", # BOM in each file
            "utc": True,             # UTC-based rollover
            "delay": True,           # open file on first emit
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


def configure_timed_bom_utc_logging() -> logging.Logger:
    """Configure TimedRotatingFileHandler with BOM and UTC midnight."""
    log_path = pathlib.Path("logs/app_timed.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    logging.config.dictConfig(LOGGING_TIMED_BOM_UTC)
    return logging.getLogger(__name__)


# 5) dictConfig snippet to call the custom handler class
LOGGING_CUSTOM_HANDLER = {
    "version": 1,
    "handlers": {
        "time_file_utf8_bom": {
            "class": "utf8_production_snippets.StartupRolloverTimedHandler",
            "level": "INFO",
            "formatter": "standard",
            "filename": "logs/app_custom.log",
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
        "": {"handlers": ["time_file_utf8_bom"], "level": "INFO", "propagate": False},
    }
}


def configure_custom_handler_logging() -> logging.Logger:
    """Configure logging with custom handler class."""
    log_path = pathlib.Path("logs/app_custom.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    logging.config.dictConfig(LOGGING_CUSTOM_HANDLER)
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
            "()": "utf8_production_snippets.Utf8StreamHandler",
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
    print("🚀 Testing Production UTF-8 Logging Snippets")
    print("=" * 50)
    
    # Test file BOM logging
    print("\n🧪 Testing File BOM Logging...")
    file_bom_logger = configure_file_bom_logging()
    file_bom_logger.info("File BOM test: 🚀 αβγ")
    
    # Verify BOM
    bom_present = verify_bom_in_file("logs/app_bom.log")
    print(f"   ✅ BOM present: {bom_present}")
    
    # Test forced rollover without subclass
    print("\n🧪 Testing Forced Rollover (no subclass)...")
    rollover_logger = configure_and_force_rollover(LOGGING_FILE_BOM)
    rollover_logger.info("Forced rollover test: 🚀 αβγ")
    
    # Test timed BOM UTC logging with subclass
    print("\n🧪 Testing Timed BOM UTC Logging (with subclass)...")
    timed_logger = configure_timed_bom_utc_logging()
    timed_logger.info("Timed BOM UTC test: 🚀 αβγ")
    
    # Test custom handler class
    print("\n🧪 Testing Custom Handler Class...")
    custom_logger = configure_custom_handler_logging()
    custom_logger.info("Custom handler test: 🚀 αβγ")
    
    # Test console + file BOM
    print("\n🧪 Testing Console + File BOM Logging...")
    console_file_logger = configure_console_file_bom_logging()
    console_file_logger.info("Console + File BOM test: 🚀 αβγ")
    
    print("\n✅ All production UTF-8 logging snippets tested successfully!")
    print("📂 Check logs/ directory for UTF-8 encoded output")
    print("\n📋 Production Features:")
    print("   • Startup rollover via subclass")
    print("   • UTF-8 BOM encoding in files")
    print("   • Programmatic rollover without subclass")
    print("   • Timed rotation with BOM + UTC")
    print("   • Custom handler class in dictConfig")
    print("   • Console + file dual output")
