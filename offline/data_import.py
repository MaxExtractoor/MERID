"""
Data Importer for Offline Mode.

Supports importing market data from various sources:
- CSV files
- JSON files
- USB drives
- Manual entry

Version: 1.0.0
"""

from __future__ import annotations

import os
import csv
import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum

from offline.data_cache import LocalDataCache, get_local_data_cache, CacheType
from utils.logger import get_logger

logger = get_logger("offline.data_import")


class ImportFormat(Enum):
    """Supported import formats."""
    CSV = "csv"
    JSON = "json"
    PARQUET = "parquet"
    MERID_EXPORT = "merid_export"


class ImportStatus(Enum):
    """Status of an import job."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ImportJob:
    """An import job."""
    job_id: str
    source_path: str
    import_format: ImportFormat
    status: ImportStatus = ImportStatus.PENDING
    
    # Progress
    total_records: int = 0
    imported_records: int = 0
    failed_records: int = 0
    
    # Timing
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    
    # Results
    errors: List[str] = field(default_factory=list)
    
    def progress_pct(self) -> float:
        if self.total_records == 0:
            return 0.0
        return (self.imported_records / self.total_records) * 100
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "source_path": self.source_path,
            "import_format": self.import_format.value,
            "status": self.status.value,
            "total_records": self.total_records,
            "imported_records": self.imported_records,
            "failed_records": self.failed_records,
            "progress_pct": self.progress_pct(),
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "errors": self.errors[-10:],  # Last 10 errors
        }


class DataImporter:
    """
    Imports market data from external sources.
    
    Features:
    - Multiple format support (CSV, JSON, Parquet)
    - USB drive detection
    - Progress tracking
    - Validation and error handling
    """
    
    def __init__(self):
        self.logger = get_logger("offline.data_import")
        self._cache = get_local_data_cache()
        
        # Import jobs
        self._jobs: Dict[str, ImportJob] = {}
        
        # Configuration
        self._import_dir = Path("data/imports")
        self._import_dir.mkdir(parents=True, exist_ok=True)
    
    def create_import_job(
        self,
        source_path: str,
        import_format: ImportFormat,
    ) -> ImportJob:
        """Create a new import job."""
        import uuid
        
        job_id = f"import_{uuid.uuid4().hex[:8]}"
        
        job = ImportJob(
            job_id=job_id,
            source_path=source_path,
            import_format=import_format,
        )
        
        self._jobs[job_id] = job
        self.logger.info(f"Created import job: {job_id}")
        
        return job
    
    async def run_import(self, job_id: str) -> bool:
        """Run an import job."""
        job = self._jobs.get(job_id)
        if not job:
            return False
        
        job.status = ImportStatus.RUNNING
        job.started_at = time.time()
        
        try:
            if job.import_format == ImportFormat.CSV:
                await self._import_csv(job)
            elif job.import_format == ImportFormat.JSON:
                await self._import_json(job)
            elif job.import_format == ImportFormat.MERID_EXPORT:
                await self._import_merid_export(job)
            else:
                raise ValueError(f"Unsupported format: {job.import_format}")
            
            job.status = ImportStatus.COMPLETED
            job.completed_at = time.time()
            
            self.logger.info(
                f"Import completed: {job_id} - "
                f"{job.imported_records}/{job.total_records} records"
            )
            return True
            
        except Exception as e:
            job.status = ImportStatus.FAILED
            job.errors.append(str(e))
            job.completed_at = time.time()
            self.logger.error(f"Import failed: {e}")
            return False
    
    async def _import_csv(self, job: ImportJob) -> None:
        """Import from CSV file."""
        path = Path(job.source_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        
        with open(path, "r", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            job.total_records = len(rows)
            
            for row in rows:
                try:
                    # Detect data type and import
                    if "open" in row and "high" in row and "low" in row and "close" in row:
                        # OHLCV data
                        self._import_ohlcv_row(row)
                    elif "price" in row:
                        # Price data
                        self._import_price_row(row)
                    else:
                        # Generic data
                        self._import_generic_row(row)
                    
                    job.imported_records += 1
                    
                except Exception as e:
                    job.failed_records += 1
                    job.errors.append(f"Row error: {e}")
    
    async def _import_json(self, job: ImportJob) -> None:
        """Import from JSON file."""
        path = Path(job.source_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        
        with open(path, "r") as f:
            data = json.load(f)
        
        # Handle array or object
        if isinstance(data, list):
            records = data
        elif isinstance(data, dict):
            records = data.get("data", data.get("records", [data]))
        else:
            records = [data]
        
        job.total_records = len(records)
        
        for record in records:
            try:
                self._import_json_record(record)
                job.imported_records += 1
            except Exception as e:
                job.failed_records += 1
                job.errors.append(f"Record error: {e}")
    
    async def _import_merid_export(self, job: ImportJob) -> None:
        """Import from MERID export format."""
        path = Path(job.source_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        
        with open(path, "r") as f:
            export_data = json.load(f)
        
        # Validate export format
        if export_data.get("format") != "merid_export":
            raise ValueError("Invalid MERID export format")
        
        # Import each section
        sections = ["prices", "ohlcv", "consensus", "intents", "executions"]
        
        for section in sections:
            section_data = export_data.get(section, [])
            job.total_records += len(section_data)
        
        # Import prices
        for price in export_data.get("prices", []):
            try:
                self._cache.cache_price_data(
                    symbol=price["symbol"],
                    price=price["price"],
                    timestamp=price["timestamp"],
                    source=price.get("source", "import"),
                )
                job.imported_records += 1
            except Exception as e:
                job.failed_records += 1
                job.errors.append(f"Price error: {e}")
        
        # Import OHLCV
        for ohlcv in export_data.get("ohlcv", []):
            try:
                self._cache.cache_ohlcv(
                    symbol=ohlcv["symbol"],
                    timeframe=ohlcv["timeframe"],
                    candles=ohlcv["candles"],
                )
                job.imported_records += 1
            except Exception as e:
                job.failed_records += 1
                job.errors.append(f"OHLCV error: {e}")
        
        # Import consensus
        for consensus in export_data.get("consensus", []):
            try:
                self._cache.cache_consensus(consensus)
                job.imported_records += 1
            except Exception as e:
                job.failed_records += 1
                job.errors.append(f"Consensus error: {e}")
    
    def _import_ohlcv_row(self, row: Dict[str, str]) -> None:
        """Import a single OHLCV row."""
        candle = {
            "timestamp": float(row.get("timestamp", time.time())),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row.get("volume", 0)),
        }
        
        symbol = row.get("symbol", "UNKNOWN")
        timeframe = row.get("timeframe", "1h")
        
        # Get existing candles and append
        existing = self._cache.get_cached_ohlcv(symbol, timeframe) or []
        existing.append(candle)
        
        self._cache.cache_ohlcv(symbol, timeframe, existing)
    
    def _import_price_row(self, row: Dict[str, str]) -> None:
        """Import a single price row."""
        self._cache.cache_price_data(
            symbol=row.get("symbol", "UNKNOWN"),
            price=float(row["price"]),
            timestamp=float(row.get("timestamp", time.time())),
            source=row.get("source", "csv_import"),
        )
    
    def _import_generic_row(self, row: Dict[str, str]) -> None:
        """Import a generic row."""
        key = f"generic_{int(time.time() * 1000)}"
        self._cache.set(CacheType.SYSTEM_STATE, key, dict(row))
    
    def _import_json_record(self, record: Dict[str, Any]) -> None:
        """Import a JSON record."""
        record_type = record.get("type", "unknown")
        
        if record_type == "price":
            self._cache.cache_price_data(
                symbol=record["symbol"],
                price=record["price"],
                timestamp=record.get("timestamp", time.time()),
                source=record.get("source", "json_import"),
            )
        elif record_type == "ohlcv":
            self._cache.cache_ohlcv(
                symbol=record["symbol"],
                timeframe=record["timeframe"],
                candles=record["candles"],
            )
        elif record_type == "consensus":
            self._cache.cache_consensus(record)
        else:
            # Generic
            key = f"json_{int(time.time() * 1000)}"
            self._cache.set(CacheType.SYSTEM_STATE, key, record)
    
    def scan_usb_drives(self) -> List[Dict[str, Any]]:
        """Scan for USB drives with importable data."""
        drives = []
        
        # Windows drive letters
        if os.name == "nt":
            import string
            for letter in string.ascii_uppercase:
                drive_path = f"{letter}:\\"
                if os.path.exists(drive_path):
                    # Check for MERID data
                    merid_path = Path(drive_path) / "merid_data"
                    if merid_path.exists():
                        drives.append({
                            "path": str(merid_path),
                            "drive": letter,
                            "type": "usb",
                            "has_merid_data": True,
                        })
        
        # Unix mount points
        else:
            media_paths = ["/media", "/mnt", "/run/media"]
            for media_path in media_paths:
                if os.path.exists(media_path):
                    for mount in os.listdir(media_path):
                        mount_path = Path(media_path) / mount
                        merid_path = mount_path / "merid_data"
                        if merid_path.exists():
                            drives.append({
                                "path": str(merid_path),
                                "mount": str(mount_path),
                                "type": "usb",
                                "has_merid_data": True,
                            })
        
        return drives
    
    def list_importable_files(self, directory: str) -> List[Dict[str, Any]]:
        """List importable files in a directory."""
        files = []
        dir_path = Path(directory)
        
        if not dir_path.exists():
            return files
        
        supported_extensions = {".csv", ".json", ".merid"}
        
        for file_path in dir_path.rglob("*"):
            if file_path.is_file() and file_path.suffix.lower() in supported_extensions:
                files.append({
                    "path": str(file_path),
                    "name": file_path.name,
                    "format": file_path.suffix.lower()[1:],
                    "size_bytes": file_path.stat().st_size,
                    "modified": file_path.stat().st_mtime,
                })
        
        return files
    
    def get_job(self, job_id: str) -> Optional[ImportJob]:
        """Get an import job."""
        return self._jobs.get(job_id)
    
    def get_status(self) -> Dict[str, Any]:
        """Get importer status."""
        return {
            "import_dir": str(self._import_dir),
            "jobs": {k: v.to_dict() for k, v in self._jobs.items()},
            "usb_drives": self.scan_usb_drives(),
        }


# Singleton
_data_importer: Optional[DataImporter] = None


def get_data_importer() -> DataImporter:
    """Get or create the Data Importer singleton."""
    global _data_importer
    if _data_importer is None:
        _data_importer = DataImporter()
    return _data_importer
