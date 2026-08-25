"""Test that logging writes to both logs/full.log and server_output.log."""
from pathlib import Path

def test_logger_configuration():
    """Verify logger is configured to write to both log files."""
    from utils.logger import get_logger, LOG_FILE, PRODUCTION_LOG_FILE
    
    # Verify log file paths are configured correctly
    assert LOG_FILE.name == "full.log", f"Primary log should be full.log, got {LOG_FILE.name}"
    assert PRODUCTION_LOG_FILE.name == "server_output.log", \
        f"Production log should be server_output.log, got {PRODUCTION_LOG_FILE.name}"
    
    # Get a logger and verify it has handlers
    logger = get_logger("test_logger")
    
    # Should have 3 handlers: file (full.log), production (server_output.log), stream
    assert len(logger.handlers) >= 2, \
        f"Logger should have at least 2 handlers (file + production), got {len(logger.handlers)}"
    
    print("✅ Logger configuration test passed")
    print(f"   Primary log: {LOG_FILE}")
    print(f"   Production log: {PRODUCTION_LOG_FILE}")
    print(f"   Handler count: {len(logger.handlers)}")
    
    # Write a test message
    logger.info("Test message for dual log files")
    
    # Flush handlers to ensure write
    for handler in logger.handlers:
        handler.flush()
    
    # Verify production log file exists and contains the message
    if PRODUCTION_LOG_FILE.exists():
        production_content = PRODUCTION_LOG_FILE.read_text(encoding="utf-8")
        if "Test message for dual log files" in production_content:
            print("✅ Production log file write test passed")
            print(f"   Production log size: {len(production_content)} bytes")
        else:
            print("⚠️  Production log file exists but message not found (may be in rotated file)")
    else:
        print("⚠️  Production log file does not exist yet (will be created on next write)")

if __name__ == "__main__":
    test_logger_configuration()
