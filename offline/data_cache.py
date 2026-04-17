"""
Local Data Cache for Offline Mode.

Provides persistent local storage of market data, consensus history,
and system state for offline operation.

Version: 1.0.0
"""

from __future__ import annotations

import threading
import os
import json
import time
import gzip
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum

from utils.logger import get_logger

logger = get_logger("offline.data_cache")


class CacheType(Enum):
    """Types of cached data."""
    PRICE_DATA = "price_data"
    OHLCV = "ohlcv"
    ORDER_BOOK = "order_book"
    CONSENSUS = "consensus"
    INTENT = "intent"
    EXECUTION = "execution"
    AGENT_STATE = "agent_state"
    SYSTEM_STATE = "system_state"


@dataclass
class CacheEntry:
    """A single cache entry."""
    cache_id: str
    cache_type: CacheType
    key: str
    data: Any
    timestamp: float = field(default_factory=time.time)
    expires_at: Optional[float] = None
    compressed: bool = False
    checksum: str = ""
    
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at
    
    def compute_checksum(self) -> str:
        """Compute checksum of data."""
        data_str = json.dumps(self.data, sort_keys=True)
        return hashlib.sha256(data_str.encode()).hexdigest()[:16]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "cache_id": self.cache_id,
            "cache_type": self.cache_type.value,
            "key": self.key,
            "data": self.data,
            "timestamp": self.timestamp,
            "expires_at": self.expires_at,
            "compressed": self.compressed,
            "checksum": self.checksum,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CacheEntry":
        return cls(
            cache_id=data["cache_id"],
            cache_type=CacheType(data["cache_type"]),
            key=data["key"],
            data=data["data"],
            timestamp=data.get("timestamp", time.time()),
            expires_at=data.get("expires_at"),
            compressed=data.get("compressed", False),
            checksum=data.get("checksum", ""),
        )


class LocalDataCache:
    """
    Local data cache for offline operation.
    
    Features:
    - Persistent storage to disk
    - Compression for large datasets
    - TTL-based expiration
    - Checksum verification
    - Incremental sync support
    """
    
    def __init__(self, cache_dir: str = "data/offline_cache"):
        self.logger = get_logger("offline.data_cache")
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # In-memory cache
        self._cache: Dict[str, CacheEntry] = {}
        
        # Cache metadata
        self._metadata: Dict[str, Any] = {
            "created_at": time.time(),
            "last_sync": None,
            "total_entries": 0,
            "total_size_bytes": 0,
        }
        
        # Configuration
        self._max_memory_entries: int = 10000
        self._default_ttl_seconds: float = 86400 * 7  # 7 days
        self._compression_threshold_bytes: int = 10000
        
        # Load existing cache
        self._load_metadata()
    
    def _load_metadata(self) -> None:
        """Load cache metadata from disk."""
        meta_path = self.cache_dir / "metadata.json"
        if meta_path.exists():
            try:
                with open(meta_path, "r") as f:
                    self._metadata = json.load(f)
                self.logger.info(f"Loaded cache metadata: {self._metadata['total_entries']} entries")
            except Exception as e:
                self.logger.error(f"Failed to load metadata: {e}")
    
    def _save_metadata(self) -> None:
        """Save cache metadata to disk."""
        meta_path = self.cache_dir / "metadata.json"
        try:
            with open(meta_path, "w") as f:
                json.dump(self._metadata, f, indent=2)
        except Exception as e:
            self.logger.error(f"Failed to save metadata: {e}")
    
    def _get_cache_path(self, cache_type: CacheType, key: str) -> Path:
        """Get file path for a cache entry."""
        type_dir = self.cache_dir / cache_type.value
        type_dir.mkdir(exist_ok=True)
        safe_key = hashlib.md5(key.encode()).hexdigest()
        return type_dir / f"{safe_key}.json"
    
    def set(
        self,
        cache_type: CacheType,
        key: str,
        data: Any,
        ttl_seconds: Optional[float] = None,
        persist: bool = True,
    ) -> str:
        """Set a cache entry."""
        import uuid
        
        cache_id = f"cache_{uuid.uuid4().hex[:12]}"
        
        entry = CacheEntry(
            cache_id=cache_id,
            cache_type=cache_type,
            key=key,
            data=data,
            expires_at=time.time() + (ttl_seconds or self._default_ttl_seconds),
        )
        entry.checksum = entry.compute_checksum()
        
        # Store in memory
        cache_key = f"{cache_type.value}:{key}"
        self._cache[cache_key] = entry
        
        # Persist to disk
        if persist:
            self._persist_entry(entry)
        
        # Update metadata
        self._metadata["total_entries"] = len(self._cache)
        self._metadata["last_sync"] = time.time()
        
        # Trim memory cache if needed
        if len(self._cache) > self._max_memory_entries:
            self._trim_memory_cache()
        
        return cache_id
    
    def get(
        self,
        cache_type: CacheType,
        key: str,
        load_from_disk: bool = True,
    ) -> Optional[Any]:
        """Get a cache entry."""
        cache_key = f"{cache_type.value}:{key}"
        
        # Check memory cache
        entry = self._cache.get(cache_key)
        
        # Try disk if not in memory
        if entry is None and load_from_disk:
            entry = self._load_entry(cache_type, key)
            if entry:
                self._cache[cache_key] = entry
        
        if entry is None:
            return None
        
        # Check expiration
        if entry.is_expired():
            self.delete(cache_type, key)
            return None
        
        # Verify checksum
        if entry.checksum and entry.compute_checksum() != entry.checksum:
            self.logger.warning(f"Checksum mismatch for {cache_key}")
            return None
        
        return entry.data
    
    def delete(self, cache_type: CacheType, key: str) -> bool:
        """Delete a cache entry."""
        cache_key = f"{cache_type.value}:{key}"
        
        # Remove from memory
        if cache_key in self._cache:
            del self._cache[cache_key]
        
        # Remove from disk
        cache_path = self._get_cache_path(cache_type, key)
        if cache_path.exists():
            cache_path.unlink()
        
        self._metadata["total_entries"] = len(self._cache)
        return True
    
    def _persist_entry(self, entry: CacheEntry) -> None:
        """Persist entry to disk."""
        cache_path = self._get_cache_path(entry.cache_type, entry.key)
        
        try:
            data_str = json.dumps(entry.to_dict())
            
            # Compress if large
            if len(data_str) > self._compression_threshold_bytes:
                compressed = gzip.compress(data_str.encode())
                with open(str(cache_path) + ".gz", "wb") as f:
                    f.write(compressed)
                entry.compressed = True
            else:
                with open(cache_path, "w") as f:
                    f.write(data_str)
                    
        except Exception as e:
            self.logger.error(f"Failed to persist entry: {e}")
    
    def _load_entry(self, cache_type: CacheType, key: str) -> Optional[CacheEntry]:
        """Load entry from disk."""
        cache_path = self._get_cache_path(cache_type, key)
        
        try:
            # Try compressed first
            gz_path = Path(str(cache_path) + ".gz")
            if gz_path.exists():
                with gzip.open(gz_path, "rt") as f:
                    data = json.load(f)
                return CacheEntry.from_dict(data)
            
            # Try uncompressed
            if cache_path.exists():
                with open(cache_path, "r") as f:
                    data = json.load(f)
                return CacheEntry.from_dict(data)
                
        except Exception as e:
            self.logger.error(f"Failed to load entry: {e}")
        
        return None
    
    def _trim_memory_cache(self) -> None:
        """Trim memory cache to max size."""
        if len(self._cache) <= self._max_memory_entries:
            return
        
        # Remove oldest entries
        sorted_entries = sorted(
            self._cache.items(),
            key=lambda x: x[1].timestamp
        )
        
        to_remove = len(self._cache) - self._max_memory_entries
        for cache_key, _ in sorted_entries[:to_remove]:
            del self._cache[cache_key]
    
    def cache_price_data(
        self,
        symbol: str,
        price: float,
        timestamp: float,
        source: str = "",
    ) -> str:
        """Cache price data."""
        key = f"{symbol}_{int(timestamp)}"
        data = {
            "symbol": symbol,
            "price": price,
            "timestamp": timestamp,
            "source": source,
        }
        return self.set(CacheType.PRICE_DATA, key, data)
    
    def cache_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        candles: List[Dict[str, Any]],
    ) -> str:
        """Cache OHLCV data."""
        key = f"{symbol}_{timeframe}"
        data = {
            "symbol": symbol,
            "timeframe": timeframe,
            "candles": candles,
            "count": len(candles),
        }
        return self.set(CacheType.OHLCV, key, data, ttl_seconds=86400 * 30)  # 30 days
    
    def cache_consensus(self, consensus_block: Dict[str, Any]) -> str:
        """Cache a consensus block."""
        key = consensus_block.get("block_id", f"block_{int(time.time())}")
        return self.set(CacheType.CONSENSUS, key, consensus_block, ttl_seconds=86400 * 365)
    
    def cache_system_state(self, state: Dict[str, Any]) -> str:
        """Cache system state snapshot."""
        key = f"state_{int(time.time())}"
        return self.set(CacheType.SYSTEM_STATE, key, state)
    
    def get_cached_prices(self, symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get cached prices for a symbol."""
        prices = []
        type_dir = self.cache_dir / CacheType.PRICE_DATA.value
        
        if not type_dir.exists():
            return prices
        
        for cache_file in type_dir.glob(f"*.json"):
            try:
                with open(cache_file, "r") as f:
                    entry_data = json.load(f)
                    if entry_data.get("data", {}).get("symbol") == symbol:
                        prices.append(entry_data["data"])
            except Exception as _cf_exc:
                logger.debug("Cache file read failed for %s: %s", cache_file, _cf_exc)
        
        prices.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        return prices[:limit]
    
    def get_cached_ohlcv(self, symbol: str, timeframe: str) -> Optional[List[Dict[str, Any]]]:
        """Get cached OHLCV data."""
        data = self.get(CacheType.OHLCV, f"{symbol}_{timeframe}")
        if data:
            return data.get("candles", [])
        return None
    
    def clear_expired(self) -> int:
        """Clear expired entries."""
        expired_count = 0
        
        for cache_key, entry in list(self._cache.items()):
            if entry.is_expired():
                cache_type, key = cache_key.split(":", 1)
                self.delete(CacheType(cache_type), key)
                expired_count += 1
        
        return expired_count
    
    def clear_all(self) -> None:
        """Clear all cached data."""
        self._cache.clear()
        
        # Remove all cache files
        import shutil
        for type_dir in self.cache_dir.iterdir():
            if type_dir.is_dir():
                shutil.rmtree(type_dir)
        
        self._metadata["total_entries"] = 0
        self._save_metadata()
        
        self.logger.warning("All cache data cleared")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        # Calculate disk usage
        total_size = 0
        file_count = 0
        
        for type_dir in self.cache_dir.iterdir():
            if type_dir.is_dir():
                for cache_file in type_dir.iterdir():
                    total_size += cache_file.stat().st_size
                    file_count += 1
        
        return {
            "memory_entries": len(self._cache),
            "disk_files": file_count,
            "disk_size_mb": round(total_size / (1024 * 1024), 2),
            "last_sync": self._metadata.get("last_sync"),
            "cache_dir": str(self.cache_dir),
        }


# Singleton
_local_data_cache: Optional[LocalDataCache] = None
_local_data_cache_lock = threading.Lock()


def get_local_data_cache() -> LocalDataCache:
    """Get or create the Local Data Cache singleton."""
    global _local_data_cache
    if _local_data_cache is None:
        with _local_data_cache_lock:
            if _local_data_cache is None:
                _local_data_cache = LocalDataCache()
    return _local_data_cache
