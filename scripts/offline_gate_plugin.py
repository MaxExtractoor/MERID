"""Deny network egress throughout offline acceptance collection and execution."""
import socket
import threading
import traceback

import pytest


_attempts = []
_local = threading.local()
_original_socketpair = socket.socketpair
_original_connect = socket.socket.connect
_original_connect_ex = socket.socket.connect_ex
_original_sendto = socket.socket.sendto


def _socketpair(*args, **kwargs):
    _local.socketpair = True
    try:
        return _original_socketpair(*args, **kwargs)
    finally:
        _local.socketpair = False


def _deny(sock, address):
    if sock.family in (socket.AF_INET, socket.AF_INET6) and not getattr(_local, "socketpair", False):
        _attempts.append(f"{address}: {''.join(traceback.format_stack(limit=12))}")
        raise OSError("Network access is forbidden in the offline acceptance gate")


def _connect(sock, address):
    _deny(sock, address)
    return _original_connect(sock, address)


def _connect_ex(sock, address):
    _deny(sock, address)
    return _original_connect_ex(sock, address)


def _sendto(sock, *args):
    _deny(sock, args[-1])
    return _original_sendto(sock, *args)


socket.socketpair = _socketpair
socket.socket.connect = _connect
socket.socket.connect_ex = _connect_ex
socket.socket.sendto = _sendto


def pytest_configure(config):
    for plugin in config.pluginmanager.get_plugins():
        if hasattr(plugin, "_live_server_running"):
            plugin._live_server_running = lambda: False


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    if _attempts:
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        if reporter is not None:
            reporter.write_line(f"Offline gate blocked {len(_attempts)} network attempts:")
            for attempt in _attempts:
                reporter.write_line(attempt)
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
