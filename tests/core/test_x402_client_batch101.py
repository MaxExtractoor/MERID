"""Tests for core/x402_payments.py - Batch 101."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, AsyncMock

from core.x402_payments import (
    PaymentRail, PaymentStatus, PaymentRequest, PaymentReceipt,
    X402Resource, X402Client
)


class TestX402Client:
    """Tests for X402Client."""

    def test_client_initialization(self):
        with patch('core.x402_payments.get_network_client') as mock_network, \
             patch('core.x402_payments.get_environment_flags') as mock_env:
            mock_network.return_value = MagicMock()
            mock_env.return_value = MagicMock()
            client = X402Client()
            assert client is not None

    def test_client_has_network_client(self):
        with patch('core.x402_payments.get_network_client') as mock_network, \
             patch('core.x402_payments.get_environment_flags') as mock_env:
            mock_network.return_value = MagicMock()
            mock_env.return_value = MagicMock()
            client = X402Client()
            assert client._network_client is not None
