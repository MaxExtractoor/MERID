"""
Runtime origin tracing utility for detecting which module/class implementations are actually used at runtime.

This helps identify when multiple versions of the same class exist and which one is being called.
"""

import inspect
import logging
import sys
import os
from typing import Any, Optional
from datetime import datetime, timezone

logger = logging.getLogger("origin_tracer")

def log_object_origin(obj: Any, label: str, context: str = "") -> None:
    """
    Log the origin (module, file, id) of an object at runtime.
    
    Args:
        obj: The object to trace (class instance, class, or function)
        label: Human-readable label for this object (e.g., "agent_grid_instance")
        context: Additional context (e.g., "in 15m loop")
    """
    try:
        mod = inspect.getmodule(obj)
        mod_name = getattr(mod, "__name__", None) if mod else None
        mod_file = getattr(mod, "__file__", None) if mod else None
        
        # For class instances, get the class info
        if not inspect.isclass(obj) and not inspect.isfunction(obj):
            class_name = type(obj).__name__
            class_module = inspect.getmodule(type(obj))
            class_mod_name = getattr(class_module, "__name__", None) if class_module else None
            class_mod_file = getattr(class_module, "__file__", None) if class_module else None
        else:
            class_name = getattr(obj, "__name__", getattr(obj, "__qualname__", str(obj)))
            class_mod_name = mod_name
            class_mod_file = mod_file
        
        obj_id = id(obj)
        timestamp = datetime.now(timezone.utc).isoformat()
        
        log_msg = (
            f"[ORIGIN-TRACE] {timestamp} | label={label} | context={context} | "
            f"obj_id={obj_id} | class={class_name} | "
            f"module={class_mod_name} | file={class_mod_file}"
        )
        
        logger.info(log_msg)
        print(log_msg, flush=True)  # Ensure it appears in stdout
        
        # Also write to a dedicated trace file for post-mortem analysis
        trace_file = os.path.join(os.getcwd(), "output", "origin_trace.log")
        os.makedirs(os.path.dirname(trace_file), exist_ok=True)
        with open(trace_file, "a") as f:
            f.write(log_msg + "\n")
            
    except Exception as e:
        logger.error(f"[ORIGIN-TRACE] Failed to trace object {label}: {e}", exc_info=True)


def log_method_entry(obj: Any, method_name: str, label: str = "") -> None:
    """
    Log when a method is about to be called, with origin info.
    
    Args:
        obj: The object whose method is being called
        method_name: Name of the method being called
        label: Additional label for context
    """
    try:
        mod = inspect.getmodule(obj)
        mod_name = getattr(mod, "__name__", None) if mod else None
        mod_file = getattr(mod, "__file__", None) if mod else None
        class_name = type(obj).__name__ if not inspect.isclass(obj) else getattr(obj, "__name__", str(obj))
        
        obj_id = id(obj)
        timestamp = datetime.now(timezone.utc).isoformat()
        
        log_msg = (
            f"[METHOD-ENTRY] {timestamp} | label={label} | method={method_name} | "
            f"obj_id={obj_id} | class={class_name} | "
            f"module={mod_name} | file={mod_file}"
        )
        
        logger.info(log_msg)
        print(log_msg, flush=True)
        
        trace_file = os.path.join(os.getcwd(), "output", "origin_trace.log")
        os.makedirs(os.path.dirname(trace_file), exist_ok=True)
        with open(trace_file, "a") as f:
            f.write(log_msg + "\n")
            
    except Exception as e:
        logger.error(f"[METHOD-ENTRY] Failed to trace method {method_name}: {e}", exc_info=True)


def log_call_stack(label: str = "") -> None:
    """
    Log the current call stack to understand who called a function.
    
    Args:
        label: Label for this stack trace
    """
    try:
        timestamp = datetime.now(timezone.utc).isoformat()
        stack = inspect.stack()
        
        log_msg = f"[CALL-STACK] {timestamp} | label={label}\n"
        for frame in stack[1:6]:  # Skip current frame, show next 5
            filename = frame.filename
            lineno = frame.lineno
            function = frame.function
            log_msg += f"  {filename}:{lineno} in {function}\n"
        
        logger.info(log_msg)
        print(log_msg, flush=True)
        
        trace_file = os.path.join(os.getcwd(), "output", "origin_trace.log")
        os.makedirs(os.path.dirname(trace_file), exist_ok=True)
        with open(trace_file, "a") as f:
            f.write(log_msg + "\n")
            
    except Exception as e:
        logger.error(f"[CALL-STACK] Failed to log stack: {e}", exc_info=True)


def verify_module_source(expected_module: str, expected_file_substring: str) -> bool:
    """
    Verify that a module is loaded from the expected source.
    
    Args:
        expected_module: Module name to check (e.g., "merid.prediction.agent_grid_15m")
        expected_file_substring: Expected substring in the file path
        
    Returns:
        True if module is loaded from expected source, False otherwise
    """
    if expected_module not in sys.modules:
        logger.warning(f"[VERIFY] Module {expected_module} not loaded")
        return False
    
    mod = sys.modules[expected_module]
    mod_file = getattr(mod, "__file__", None)
    
    if mod_file is None:
        logger.warning(f"[VERIFY] Module {expected_module} has no __file__ attribute")
        return False
    
    is_expected = expected_file_substring in mod_file
    
    log_msg = (
        f"[VERIFY-MODULE] module={expected_module} | "
        f"actual_file={mod_file} | expected_contains={expected_file_substring} | "
        f"match={is_expected}"
    )
    
    logger.info(log_msg)
    print(log_msg, flush=True)
    
    trace_file = os.path.join(os.getcwd(), "output", "origin_trace.log")
    os.makedirs(os.path.dirname(trace_file), exist_ok=True)
    with open(trace_file, "a") as f:
        f.write(log_msg + "\n")
    
    return is_expected


def log_sys_path() -> None:
    """Log the current sys.path to detect multiple installations."""
    timestamp = datetime.now(timezone.utc).isoformat()
    log_msg = f"[SYS-PATH] {timestamp}\n"
    
    for i, path in enumerate(sys.path):
        log_msg += f"  [{i}] {path}\n"
    
    logger.info(log_msg)
    print(log_msg, flush=True)
    
    trace_file = os.path.join(os.getcwd(), "output", "origin_trace.log")
    os.makedirs(os.path.dirname(trace_file), exist_ok=True)
    with open(trace_file, "a") as f:
        f.write(log_msg + "\n")


def log_environment() -> None:
    """Log relevant environment variables."""
    timestamp = datetime.now(timezone.utc).isoformat()
    env_vars = [
        "MERID_PROFILE",
        "MERID_ALLOW_LIVE_TRADES",
        "KALSHI_ENV",
        "PYTHONPATH",
    ]
    
    log_msg = f"[ENVIRONMENT] {timestamp}\n"
    for var in env_vars:
        value = os.environ.get(var, "<not set>")
        log_msg += f"  {var}={value}\n"
    
    logger.info(log_msg)
    print(log_msg, flush=True)
    
    trace_file = os.path.join(os.getcwd(), "output", "origin_trace.log")
    os.makedirs(os.path.dirname(trace_file), exist_ok=True)
    with open(trace_file, "a") as f:
        f.write(log_msg + "\n")
