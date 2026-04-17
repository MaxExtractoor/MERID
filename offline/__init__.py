"""
MERID Offline / Air-Gapped Mode.

Enables sovereign operation without internet connectivity.
Supports local data caching, deterministic replay, and QR-based
signed intent transfer.

Version: 1.0.0
"""

from offline.data_cache import LocalDataCache, get_local_data_cache
from offline.replay_engine import ReplayEngine, get_replay_engine
from offline.data_import import DataImporter, get_data_importer
from offline.qr_transfer import QRIntentTransfer, get_qr_transfer
from offline.offline_mode import OfflineModeManager, get_offline_mode_manager

__all__ = [
    "LocalDataCache",
    "get_local_data_cache",
    "ReplayEngine",
    "get_replay_engine",
    "DataImporter",
    "get_data_importer",
    "QRIntentTransfer",
    "get_qr_transfer",
    "OfflineModeManager",
    "get_offline_mode_manager",
]

# Offline mode is disabled by default
OFFLINE_MODE_ENABLED = False
