"""
Hot/warm/cold data tier manager for MERID.

Implements:
- Three-tier storage architecture (hot/warm/cold)
- Automatic data lifecycle management
- Scheduled archival and compression
- On-demand rehydration for research
- Cost-optimized storage placement
"""

import logging
import asyncio
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from decimal import Decimal
import json

logger = logging.getLogger(__name__)


class DataTier(Enum):
    """Data storage tier."""
    HOT = "hot"  # Fast DBs/memory for current data
    WARM = "warm"  # Cheaper storage for recent data
    COLD = "cold"  # Archive storage for historical data


class DataCategory(Enum):
    """Data category."""
    POSITIONS = "positions"
    MARKET_DATA = "market_data"
    ORDER_BOOK = "order_book"
    TRADES = "trades"
    TELEMETRY = "telemetry"
    LOGS = "logs"
    BACKTEST_DATA = "backtest_data"
    AGENT_TRACES = "agent_traces"


class CompressionType(Enum):
    """Compression type."""
    NONE = "none"
    GZIP = "gzip"
    ZSTD = "zstd"
    PARQUET = "parquet"


@dataclass
class DataObject:
    """Data object."""
    object_id: str
    category: DataCategory
    
    # Location
    tier: DataTier
    storage_path: str
    
    # Metadata
    size_bytes: int
    record_count: int
    
    # Time range
    start_time: datetime
    end_time: datetime
    
    # Compression
    compression: CompressionType = CompressionType.NONE
    compressed_size_bytes: Optional[int] = None
    
    # Access
    last_accessed: Optional[datetime] = None
    access_count: int = 0
    
    # Lifecycle
    eligible_for_archival: bool = False
    archived_at: Optional[datetime] = None
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class TierPolicy:
    """Data tier policy."""
    policy_id: str
    category: DataCategory
    
    # Hot tier retention
    hot_retention_days: int = 7
    
    # Warm tier retention
    warm_retention_days: int = 90
    
    # Cold tier retention
    cold_retention_days: int = 3650  # 10 years
    
    # Access patterns
    min_access_count_for_hot: int = 10
    
    # Compression
    compress_warm: bool = True
    compress_cold: bool = True
    compression_type: CompressionType = CompressionType.ZSTD
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ArchivalJob:
    """Archival job."""
    job_id: str
    
    # Scope
    category: DataCategory
    from_tier: DataTier
    to_tier: DataTier
    
    # Time range
    start_time: datetime
    end_time: datetime
    
    # Progress
    total_objects: int = 0
    processed_objects: int = 0
    failed_objects: int = 0
    
    # Metrics
    bytes_processed: int = 0
    bytes_saved: int = 0
    
    # Status
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: str = ""
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class RehydrationRequest:
    """Rehydration request."""
    request_id: str
    
    # Scope
    category: DataCategory
    
    # Filters
    start_time: datetime
    end_time: datetime
    symbols: List[str] = field(default_factory=list)
    
    # Target
    target_tier: DataTier = DataTier.HOT
    
    # Requester
    requester_id: str = ""
    purpose: str = ""
    
    # Status
    status: str = "pending"  # pending, processing, completed, failed
    objects_rehydrated: int = 0
    
    created_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None


class DataTierManager:
    """
    Hot/warm/cold data tier manager.
    
    Features:
    - Three-tier storage (hot/warm/cold)
    - Automatic lifecycle management
    - Scheduled archival with compression
    - On-demand rehydration
    - Cost optimization
    """
    
    def __init__(self):
        self._data_objects: Dict[str, DataObject] = {}
        self._tier_policies: Dict[DataCategory, TierPolicy] = {}
        self._archival_jobs: List[ArchivalJob] = []
        self._rehydration_requests: Dict[str, RehydrationRequest] = {}
        
        self._initialize_policies()
    
    def _initialize_policies(self) -> None:
        """Initialize default tier policies."""
        
        # Positions - keep hot for 7 days
        self.set_tier_policy(
            category=DataCategory.POSITIONS,
            hot_retention_days=7,
            warm_retention_days=90,
            cold_retention_days=3650,
        )
        
        # Market data - keep hot for 1 day
        self.set_tier_policy(
            category=DataCategory.MARKET_DATA,
            hot_retention_days=1,
            warm_retention_days=30,
            cold_retention_days=3650,
        )
        
        # Order book - keep hot for 1 day
        self.set_tier_policy(
            category=DataCategory.ORDER_BOOK,
            hot_retention_days=1,
            warm_retention_days=7,
            cold_retention_days=365,
        )
        
        # Trades - keep hot for 7 days
        self.set_tier_policy(
            category=DataCategory.TRADES,
            hot_retention_days=7,
            warm_retention_days=90,
            cold_retention_days=3650,
        )
        
        # Telemetry - keep hot for 3 days
        self.set_tier_policy(
            category=DataCategory.TELEMETRY,
            hot_retention_days=3,
            warm_retention_days=30,
            cold_retention_days=365,
        )
        
        # Logs - keep hot for 7 days
        self.set_tier_policy(
            category=DataCategory.LOGS,
            hot_retention_days=7,
            warm_retention_days=30,
            cold_retention_days=365,
        )
        
        # Backtest data - keep warm by default
        self.set_tier_policy(
            category=DataCategory.BACKTEST_DATA,
            hot_retention_days=0,
            warm_retention_days=90,
            cold_retention_days=3650,
        )
        
        # Agent traces - keep hot for 7 days
        self.set_tier_policy(
            category=DataCategory.AGENT_TRACES,
            hot_retention_days=7,
            warm_retention_days=90,
            cold_retention_days=3650,
        )
        
        logger.info(f"Initialized {len(self._tier_policies)} tier policies")
    
    def set_tier_policy(
        self,
        category: DataCategory,
        hot_retention_days: int,
        warm_retention_days: int,
        cold_retention_days: int,
        compress_warm: bool = True,
        compress_cold: bool = True,
    ) -> TierPolicy:
        """Set tier policy for data category."""
        policy_id = f"policy_{category.value}"
        
        policy = TierPolicy(
            policy_id=policy_id,
            category=category,
            hot_retention_days=hot_retention_days,
            warm_retention_days=warm_retention_days,
            cold_retention_days=cold_retention_days,
            compress_warm=compress_warm,
            compress_cold=compress_cold,
        )
        
        self._tier_policies[category] = policy
        
        logger.info(
            f"Set tier policy for {category.value}: "
            f"hot={hot_retention_days}d, warm={warm_retention_days}d, cold={cold_retention_days}d"
        )
        
        return policy
    
    def register_data_object(
        self,
        category: DataCategory,
        tier: DataTier,
        storage_path: str,
        size_bytes: int,
        record_count: int,
        start_time: datetime,
        end_time: datetime,
    ) -> DataObject:
        """Register data object."""
        object_id = f"obj_{category.value}_{int(start_time.timestamp())}"
        
        obj = DataObject(
            object_id=object_id,
            category=category,
            tier=tier,
            storage_path=storage_path,
            size_bytes=size_bytes,
            record_count=record_count,
            start_time=start_time,
            end_time=end_time,
        )
        
        self._data_objects[object_id] = obj
        
        logger.debug(
            f"Registered data object '{object_id}': {category.value} "
            f"in {tier.value} ({size_bytes} bytes, {record_count} records)"
        )
        
        return obj
    
    def evaluate_lifecycle(self) -> List[DataObject]:
        """Evaluate data objects for lifecycle transitions."""
        now = datetime.utcnow()
        candidates = []
        
        for obj in self._data_objects.values():
            policy = self._tier_policies.get(obj.category)
            
            if not policy:
                continue
            
            age_days = (now - obj.end_time).days
            
            # Check if should move to warm
            if obj.tier == DataTier.HOT and age_days > policy.hot_retention_days:
                obj.eligible_for_archival = True
                candidates.append(obj)
                logger.info(
                    f"Object '{obj.object_id}' eligible for HOT→WARM "
                    f"(age: {age_days}d, policy: {policy.hot_retention_days}d)"
                )
            
            # Check if should move to cold
            elif obj.tier == DataTier.WARM and age_days > policy.warm_retention_days:
                obj.eligible_for_archival = True
                candidates.append(obj)
                logger.info(
                    f"Object '{obj.object_id}' eligible for WARM→COLD "
                    f"(age: {age_days}d, policy: {policy.warm_retention_days}d)"
                )
        
        return candidates
    
    async def create_archival_job(
        self,
        category: DataCategory,
        from_tier: DataTier,
        to_tier: DataTier,
        start_time: datetime,
        end_time: datetime,
    ) -> ArchivalJob:
        """Create archival job."""
        job_id = f"archive_{int(datetime.utcnow().timestamp())}"
        
        # Find objects to archive
        objects_to_archive = [
            obj for obj in self._data_objects.values()
            if obj.category == category
            and obj.tier == from_tier
            and obj.start_time >= start_time
            and obj.end_time <= end_time
            and obj.eligible_for_archival
        ]
        
        job = ArchivalJob(
            job_id=job_id,
            category=category,
            from_tier=from_tier,
            to_tier=to_tier,
            start_time=start_time,
            end_time=end_time,
            total_objects=len(objects_to_archive),
        )
        
        self._archival_jobs.append(job)
        
        logger.info(
            f"Created archival job '{job_id}': {category.value} "
            f"{from_tier.value}→{to_tier.value} ({len(objects_to_archive)} objects)"
        )
        
        # Execute job
        await self._execute_archival_job(job, objects_to_archive)
        
        return job
    
    async def _execute_archival_job(
        self,
        job: ArchivalJob,
        objects: List[DataObject],
    ) -> None:
        """Execute archival job."""
        job.started_at = datetime.utcnow()
        
        policy = self._tier_policies.get(job.category)
        
        for obj in objects:
            try:
                # Simulate compression
                if policy and (
                    (job.to_tier == DataTier.WARM and policy.compress_warm) or
                    (job.to_tier == DataTier.COLD and policy.compress_cold)
                ):
                    # Simulate compression (assume 70% compression ratio)
                    compressed_size = int(obj.size_bytes * 0.3)
                    obj.compression = policy.compression_type
                    obj.compressed_size_bytes = compressed_size
                    
                    bytes_saved = obj.size_bytes - compressed_size
                    job.bytes_saved += bytes_saved
                else:
                    compressed_size = obj.size_bytes
                
                # Update object tier
                obj.tier = job.to_tier
                obj.archived_at = datetime.utcnow()
                obj.eligible_for_archival = False
                
                # Update storage path
                obj.storage_path = f"s3://merid-{job.to_tier.value}/{obj.object_id}"
                
                job.processed_objects += 1
                job.bytes_processed += obj.size_bytes
                
                logger.debug(
                    f"Archived object '{obj.object_id}' to {job.to_tier.value} "
                    f"(saved {bytes_saved if obj.compression != CompressionType.NONE else 0} bytes)"
                )
                
                # Simulate processing delay
                await asyncio.sleep(0.001)
                
            except Exception as e:
                logger.error(f"Failed to archive object '{obj.object_id}': {e}")
                job.failed_objects += 1
        
        job.completed_at = datetime.utcnow()
        
        duration = (job.completed_at - job.started_at).total_seconds()
        
        logger.info(
            f"Archival job '{job.job_id}' completed: "
            f"{job.processed_objects}/{job.total_objects} objects in {duration:.2f}s "
            f"(saved {job.bytes_saved / 1024 / 1024:.2f} MB)"
        )
    
    async def create_rehydration_request(
        self,
        category: DataCategory,
        start_time: datetime,
        end_time: datetime,
        requester_id: str,
        purpose: str,
        symbols: Optional[List[str]] = None,
    ) -> RehydrationRequest:
        """Create rehydration request."""
        request_id = f"rehydrate_{int(datetime.utcnow().timestamp())}"
        
        request = RehydrationRequest(
            request_id=request_id,
            category=category,
            start_time=start_time,
            end_time=end_time,
            symbols=symbols or [],
            requester_id=requester_id,
            purpose=purpose,
        )
        
        self._rehydration_requests[request_id] = request
        
        logger.info(
            f"Created rehydration request '{request_id}': {category.value} "
            f"from {start_time} to {end_time} for {requester_id}"
        )
        
        # Execute rehydration
        await self._execute_rehydration(request)
        
        return request
    
    async def _execute_rehydration(self, request: RehydrationRequest) -> None:
        """Execute rehydration request."""
        request.status = "processing"
        
        # Find objects to rehydrate
        objects_to_rehydrate = [
            obj for obj in self._data_objects.values()
            if obj.category == request.category
            and obj.tier in [DataTier.WARM, DataTier.COLD]
            and obj.start_time >= request.start_time
            and obj.end_time <= request.end_time
        ]
        
        for obj in objects_to_rehydrate:
            try:
                # Decompress if needed
                if obj.compression != CompressionType.NONE:
                    logger.debug(f"Decompressing object '{obj.object_id}'")
                    obj.compression = CompressionType.NONE
                    obj.compressed_size_bytes = None
                
                # Move to hot tier
                obj.tier = request.target_tier
                obj.storage_path = f"db://hot/{obj.object_id}"
                obj.last_accessed = datetime.utcnow()
                obj.access_count += 1
                
                request.objects_rehydrated += 1
                
                logger.debug(f"Rehydrated object '{obj.object_id}' to {request.target_tier.value}")
                
                # Simulate processing delay
                await asyncio.sleep(0.001)
                
            except Exception as e:
                logger.error(f"Failed to rehydrate object '{obj.object_id}': {e}")
        
        request.status = "completed"
        request.completed_at = datetime.utcnow()
        
        logger.info(
            f"Rehydration request '{request.request_id}' completed: "
            f"{request.objects_rehydrated} objects rehydrated"
        )
    
    def get_tier_stats(self) -> Dict[str, Any]:
        """Get tier statistics."""
        stats = {
            tier.value: {
                "objects": 0,
                "total_bytes": 0,
                "compressed_bytes": 0,
                "by_category": {},
            }
            for tier in DataTier
        }
        
        for obj in self._data_objects.values():
            tier_stats = stats[obj.tier.value]
            tier_stats["objects"] += 1
            tier_stats["total_bytes"] += obj.size_bytes
            
            if obj.compressed_size_bytes:
                tier_stats["compressed_bytes"] += obj.compressed_size_bytes
            else:
                tier_stats["compressed_bytes"] += obj.size_bytes
            
            category_key = obj.category.value
            if category_key not in tier_stats["by_category"]:
                tier_stats["by_category"][category_key] = {
                    "objects": 0,
                    "bytes": 0,
                }
            
            tier_stats["by_category"][category_key]["objects"] += 1
            tier_stats["by_category"][category_key]["bytes"] += obj.size_bytes
        
        return stats
    
    def get_data_tier_dashboard(self) -> Dict[str, Any]:
        """Get data tier dashboard."""
        tier_stats = self.get_tier_stats()
        
        total_objects = sum(
            tier["objects"] for tier in tier_stats.values()
        )
        
        total_bytes = sum(
            tier["total_bytes"] for tier in tier_stats.values()
        )
        
        total_compressed = sum(
            tier["compressed_bytes"] for tier in tier_stats.values()
        )
        
        compression_ratio = (
            (total_bytes - total_compressed) / total_bytes
            if total_bytes > 0 else 0.0
        )
        
        return {
            "summary": {
                "total_objects": total_objects,
                "total_bytes": total_bytes,
                "total_compressed_bytes": total_compressed,
                "compression_ratio": compression_ratio,
                "bytes_saved": total_bytes - total_compressed,
            },
            "tiers": tier_stats,
            "archival": {
                "total_jobs": len(self._archival_jobs),
                "completed_jobs": sum(
                    1 for job in self._archival_jobs
                    if job.completed_at is not None
                ),
                "total_bytes_saved": sum(
                    job.bytes_saved for job in self._archival_jobs
                ),
            },
            "rehydration": {
                "total_requests": len(self._rehydration_requests),
                "completed_requests": sum(
                    1 for req in self._rehydration_requests.values()
                    if req.status == "completed"
                ),
            },
            "eligible_for_archival": sum(
                1 for obj in self._data_objects.values()
                if obj.eligible_for_archival
            ),
        }


_data_tier_manager: Optional[DataTierManager] = None


def get_data_tier_manager() -> DataTierManager:
    """Get global DataTierManager instance."""
    global _data_tier_manager
    if _data_tier_manager is None:
        _data_tier_manager = DataTierManager()
    return _data_tier_manager
