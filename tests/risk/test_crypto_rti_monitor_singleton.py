import pytest
import merid.risk.crypto_rti_monitor as mod
from merid.risk.crypto_rti_monitor import (
    get_global_crypto_rti_monitor,
    set_global_crypto_rti_monitor,
    CryptoRTIMonitor,
)
from unittest.mock import MagicMock


def _clear_singleton():
    mod._global_monitor = None


def test_raises_before_set():
    _clear_singleton()
    with pytest.raises(RuntimeError, match="not initialized"):
        get_global_crypto_rti_monitor()


def test_set_then_get_returns_same_instance():
    _clear_singleton()
    mock = MagicMock(spec=CryptoRTIMonitor)
    set_global_crypto_rti_monitor(mock)
    assert get_global_crypto_rti_monitor() is mock


def test_set_overwrites_previous():
    _clear_singleton()
    mock_a = MagicMock(spec=CryptoRTIMonitor)
    mock_b = MagicMock(spec=CryptoRTIMonitor)
    set_global_crypto_rti_monitor(mock_a)
    set_global_crypto_rti_monitor(mock_b)
    assert get_global_crypto_rti_monitor() is mock_b
