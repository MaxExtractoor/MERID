"""Concrete venue executors for MERID's unified execution layer.

KalshiExecutor is always available. All other executors are lazy-loaded
on first access to avoid import errors in Kalshi-only deployments.
"""

from __future__ import annotations

from .kalshi import KalshiExecutor

__all__ = [
    "KalshiExecutor",
    "AlpacaExecutor",
    "CoinbaseExecutor",
    "CryptoComExecutor",
    "CronosOnchainExecutor",
    "FulcromExecutor",
    "JupiterExecutor",
    "WebullExecutor",
]


def __getattr__(name: str):
    """Lazy-load non-Kalshi executors on first access."""
    _lazy = {
        "AlpacaExecutor": (".alpaca", "AlpacaExecutor"),
        "CoinbaseExecutor": (".coinbase", "CoinbaseExecutor"),
        "CryptoComExecutor": (".crypto_com", "CryptoComExecutor"),
        "CronosOnchainExecutor": (".cronos_onchain", "CronosOnchainExecutor"),
        "FulcromExecutor": (".fulcrom", "FulcromExecutor"),
        "JupiterExecutor": (".jupiter", "JupiterExecutor"),
        "WebullExecutor": (".webull", "WebullExecutor"),
    }
    if name in _lazy:
        module_path, class_name = _lazy[name]
        import importlib
        mod = importlib.import_module(module_path, package=__name__)
        return getattr(mod, class_name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
