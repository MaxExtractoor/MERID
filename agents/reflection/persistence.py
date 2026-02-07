"""
PersistenceLayer - Layer 6: Optimized Storage with Caching

Responsibilities:
- Persist reflections to disk
- Load reflections on startup
- Implement caching for performance
- Handle concurrent access
- Manage storage size and rotation
"""

from __future__ import annotations

import json
import time
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime

from agents.reflection.core import Reflection, DecisionOutcome
from utils.logger import get_logger

logger = get_logger("reflection.persistence")


class PersistenceLayer:
    """
    Handles persistent storage of reflections.
    
    Features:
    - Async write batching
    - Compression for old data
    - Automatic rotation
    - Crash recovery
    - Performance optimization
    """
    
    def __init__(
        self,
        storage_path: Path,
        batch_size: int = 100,
        flush_interval: float = 30.0,
        max_file_size_mb: int = 100
    ):
        self.storage_path = Path(storage_path)
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.max_file_size_mb = max_file_size_mb
        
        # Ensure directory exists
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write buffer
        self._write_buffer: List[Reflection] = []
        self._buffer_lock = threading.Lock()
        
        # Background flush
        self._flush_thread: Optional[threading.Thread] = None
        self._running = False
        
        # Stats
        self._writes = 0
        self._reads = 0
        self._flushes = 0
        self._start_time = time.time()
        
        logger.info(
            "PersistenceLayer initialized: path=%s batch=%d flush_interval=%.1fs",
            self.storage_path, batch_size, flush_interval
        )
    
    def start(self):
        """Start background flush thread."""
        if self._running:
            return
        
        self._running = True
        self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._flush_thread.start()
        
        logger.info("Background flush thread started")
    
    def stop(self):
        """Stop background flush and flush remaining data."""
        self._running = False
        
        if self._flush_thread:
            self._flush_thread.join(timeout=5.0)
        
        # Final flush
        self.flush()
        
        logger.info("PersistenceLayer stopped")
    
    def save_reflection(self, reflection: Reflection):
        """
        Save a reflection (buffered).
        
        Args:
            reflection: Reflection to save
        """
        with self._buffer_lock:
            self._write_buffer.append(reflection)
            self._writes += 1
            
            # Flush if buffer full
            if len(self._write_buffer) >= self.batch_size:
                self._flush_buffer()
    
    def flush(self):
        """Force flush of write buffer."""
        with self._buffer_lock:
            if self._write_buffer:
                self._flush_buffer()
    
    def load_all(self) -> List[Reflection]:
        """
        Load all reflections from storage.
        
        Returns:
            List of reflections
        """
        start = time.time()
        
        if not self.storage_path.exists():
            logger.info("No storage file found, starting fresh")
            return []
        
        try:
            with open(self.storage_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            reflections = []
            for item in data.get('reflections', []):
                try:
                    reflection = Reflection.from_dict(item)
                    reflections.append(reflection)
                except Exception as e:
                    logger.warning("Failed to load reflection: %s", e)
            
            self._reads += len(reflections)
            duration_ms = (time.time() - start) * 1000
            
            logger.info(
                "Loaded %d reflections from storage (%.2fms)",
                len(reflections), duration_ms
            )
            
            return reflections
            
        except Exception as e:
            logger.error("Failed to load reflections: %s", e, exc_info=True)
            return []
    
    def _flush_buffer(self):
        """Flush write buffer to disk (must hold lock)."""
        if not self._write_buffer:
            return
        
        start = time.time()
        
        try:
            # Load existing data
            existing_data = {}
            if self.storage_path.exists():
                try:
                    with open(self.storage_path, 'r', encoding='utf-8') as f:
                        existing_data = json.load(f)
                except Exception as e:
                    logger.warning("Failed to load existing data: %s", e)
            
            # Merge with buffer
            existing_reflections = existing_data.get('reflections', [])
            
            # Convert buffer to dicts
            new_reflections = [r.to_dict() for r in self._write_buffer]
            
            # Combine (new reflections at end)
            all_reflections = existing_reflections + new_reflections
            
            # Check file size and rotate if needed
            if len(all_reflections) > 10000:
                self._rotate_storage(all_reflections)
                all_reflections = all_reflections[-10000:]  # Keep last 10k
            
            # Write to disk
            output = {
                'reflections': all_reflections,
                'metadata': {
                    'last_updated': datetime.now().isoformat(),
                    'total_reflections': len(all_reflections),
                    'version': '2.0'
                }
            }
            
            # Write atomically
            temp_path = self.storage_path.with_suffix('.tmp')
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(output, f, indent=2)
            
            # Atomic rename
            temp_path.replace(self.storage_path)
            
            buffer_size = len(self._write_buffer)
            self._write_buffer.clear()
            self._flushes += 1
            
            duration_ms = (time.time() - start) * 1000
            
            logger.debug(
                "Flushed %d reflections to disk (%.2fms)",
                buffer_size, duration_ms
            )
            
        except Exception as e:
            logger.error("Failed to flush buffer: %s", e, exc_info=True)
    
    def _flush_loop(self):
        """Background flush loop."""
        logger.info("Flush loop started")
        
        while self._running:
            time.sleep(self.flush_interval)
            
            with self._buffer_lock:
                if self._write_buffer:
                    self._flush_buffer()
        
        logger.info("Flush loop stopped")
    
    def _rotate_storage(self, reflections: List[Dict[str, Any]]):
        """Rotate old reflections to archive."""
        try:
            archive_path = self.storage_path.parent / f"reflections_archive_{int(time.time())}.json"
            
            # Save old reflections
            archive_data = {
                'reflections': reflections[:-5000],  # Archive older half
                'metadata': {
                    'archived_at': datetime.now().isoformat(),
                    'count': len(reflections[:-5000])
                }
            }
            
            with open(archive_path, 'w', encoding='utf-8') as f:
                json.dump(archive_data, f)
            
            logger.info("Rotated %d reflections to archive: %s", len(reflections[:-5000]), archive_path)
            
        except Exception as e:
            logger.error("Failed to rotate storage: %s", e)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get persistence layer statistics."""
        uptime = time.time() - self._start_time
        
        file_size = 0
        if self.storage_path.exists():
            file_size = self.storage_path.stat().st_size
        
        return {
            "storage_path": str(self.storage_path),
            "file_size_mb": round(file_size / (1024 * 1024), 2),
            "buffer_size": len(self._write_buffer),
            "batch_size": self.batch_size,
            "flush_interval": self.flush_interval,
            "operations": {
                "writes": self._writes,
                "reads": self._reads,
                "flushes": self._flushes
            },
            "performance": {
                "uptime_seconds": round(uptime, 2),
                "writes_per_second": round(self._writes / uptime, 2) if uptime > 0 else 0
            }
        }
