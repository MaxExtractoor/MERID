"""Single-instance guard for the production 15m live trading server.

A second uvicorn process must never run the trading lifespan.  FastAPI runs
the lifespan *before* uvicorn binds its HTTP port, so a duplicate launched
on 2026-09-27 completed the entire live startup — WebSocket subscriptions,
REST reconciliation, the live entry loop — for ~60s before the bind failed.
Two concurrent live loops can double-submit orders and corrupt
reconciliation state.

The guard acquires a machine-scoped OS mutex before any startup side
effects take place and probes the HTTP port for an existing owner.  A
conflict aborts startup immediately so the duplicate never reaches
``LIVE_ENTRIES_ENABLED`` or places a single request against Kalshi.
"""

from __future__ import annotations

import os
import socket
import sys
import logging

logger = logging.getLogger(__name__)


class DuplicateInstanceError(RuntimeError):
    """Raised when another MERID 15m server instance already owns this runtime."""


_MUTEX_NAME = r"Local\MERID_15M_LIVE_SINGLE_INSTANCE"
_LOCK_NAME = "merid_15m_live_single_instance.lock"

# Keep the acquired handle alive for the lifetime of the process.  If the
# handle is released the mutex/lock disappears and a later duplicate could
# start while we are still running.
_held_handle = None


def _acquire_windows_mutex() -> bool:
    """Acquire the named mutex on Windows.  Returns True if this process owns it."""
    import ctypes

    ERROR_ALREADY_EXISTS = 183
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.CreateMutexW(None, True, _MUTEX_NAME)
    if not handle:
        logger.error("[SINGLE-INSTANCE] CreateMutexW failed (no handle returned)")
        return False
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        # Another live process holds the mutex.  Drop our handle to the
        # existing object and refuse to start.
        kernel32.CloseHandle(handle)
        return False
    global _held_handle
    _held_handle = handle
    return True


def _acquire_posix_lock() -> bool:
    """Acquire an exclusive advisory lockfile on POSIX.  Returns True if owned."""
    import fcntl
    import tempfile

    path = os.path.join(tempfile.gettempdir(), _LOCK_NAME)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return False
    global _held_handle
    _held_handle = fd
    return True


def _port_is_listening(port: int, host: str = "127.0.0.1", timeout: float = 0.75) -> bool:
    """Return True if something is already accepting TCP connections on port."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _resolve_port(default: int = 8011) -> int:
    """Resolve the HTTP port the server intends to bind.

    Order: MERID_HTTP_PORT env (set by start_15m.ps1), then the uvicorn
    ``--port`` / ``--port=`` CLI argument, then the production default.
    """
    env_port = os.getenv("MERID_HTTP_PORT")
    if env_port:
        try:
            return int(env_port)
        except ValueError:
            pass
    argv = sys.argv or []
    for i, arg in enumerate(argv):
        if arg in ("--port", "-p") and i + 1 < len(argv):
            try:
                return int(argv[i + 1])
            except ValueError:
                pass
        if arg.startswith("--port="):
            try:
                return int(arg.split("=", 1)[1])
            except ValueError:
                pass
    return default


def acquire_live_instance_guard(port: int | None = None) -> int:
    """Enforce single live instance ownership before any startup side effects.

    Args:
        port: HTTP port to probe for an existing owner.  ``None`` resolves it
            from MERID_HTTP_PORT / uvicorn argv / the 8011 default.

    Returns:
        The resolved port (for logging by the caller).

    Raises:
        DuplicateInstanceError: if another process already holds the mutex
            or already owns the HTTP port.
    """
    resolved_port = _resolve_port() if port is None else int(port)

    if sys.platform == "win32":
        owns_mutex = _acquire_windows_mutex()
    else:
        owns_mutex = _acquire_posix_lock()
    if not owns_mutex:
        raise DuplicateInstanceError(
            f"another MERID 15m process already holds the single-instance "
            f"mutex ({_MUTEX_NAME}) — refusing to start a duplicate live server"
        )

    if resolved_port and _port_is_listening(resolved_port):
        raise DuplicateInstanceError(
            f"port 127.0.0.1:{resolved_port} is already bound by another "
            f"process — refusing to start a duplicate live server"
        )

    logger.info(
        "[SINGLE-INSTANCE] guard acquired: mutex=%s port_probe=127.0.0.1:%s free",
        _MUTEX_NAME, resolved_port,
    )
    return resolved_port


def release_guard_for_tests() -> None:
    """Test-only helper: drop the held handle so a fresh acquire can succeed."""
    global _held_handle
    handle = _held_handle
    _held_handle = None
    if handle is None:
        return
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.ReleaseMutex(handle)
        kernel32.CloseHandle(handle)
    else:
        try:
            os.close(handle)
        except OSError:
            pass
