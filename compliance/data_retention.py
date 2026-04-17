"""
Data Retention Manager.

Manages data retention policies for regulatory compliance.
Handles archival, purging, and legal hold of data.

Version: 1.0.0
"""

from __future__ import annotations

import threading
import os
import json
import time
import shutil
import gzip
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone

from utils.logger import get_logger

logger = get_logger("compliance.retention")


class RetentionCategory(Enum):
    """Categories of data for retention."""
    TRANSACTIONS = "transactions"
    AUDIT_LOGS = "audit_logs"
    TRADE_DATA = "trade_data"
    MARKET_DATA = "market_data"
    USER_DATA = "user_data"
    SYSTEM_LOGS = "system_logs"
    REPORTS = "reports"


class RetentionAction(Enum):
    """Actions for data retention."""
    RETAIN = "retain"
    ARCHIVE = "archive"
    PURGE = "purge"
    LEGAL_HOLD = "legal_hold"


@dataclass
class RetentionPolicy:
    """A data retention policy."""
    policy_id: str
    category: RetentionCategory
    name: str
    
    # Retention periods (days)
    hot_retention_days: int = 30      # Keep in active storage
    warm_retention_days: int = 365    # Keep in archive
    cold_retention_days: int = 2555   # Keep in cold storage (7 years)
    
    # Actions
    archive_after_days: int = 30
    purge_after_days: int = 2555
    
    # Compliance
    regulatory_requirement: str = ""
    minimum_retention_days: int = 2555  # 7 years for financial
    
    # State
    enabled: bool = True
    last_run: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "category": self.category.value,
            "name": self.name,
            "hot_retention_days": self.hot_retention_days,
            "warm_retention_days": self.warm_retention_days,
            "cold_retention_days": self.cold_retention_days,
            "archive_after_days": self.archive_after_days,
            "purge_after_days": self.purge_after_days,
            "regulatory_requirement": self.regulatory_requirement,
            "minimum_retention_days": self.minimum_retention_days,
            "enabled": self.enabled,
            "last_run": self.last_run,
        }


@dataclass
class LegalHold:
    """A legal hold on data."""
    hold_id: str
    name: str
    description: str
    
    # Scope
    categories: List[RetentionCategory] = field(default_factory=list)
    start_date: Optional[float] = None
    end_date: Optional[float] = None
    
    # State
    active: bool = True
    created_at: float = field(default_factory=time.time)
    created_by: str = ""
    
    # Metadata
    case_number: str = ""
    notes: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "hold_id": self.hold_id,
            "name": self.name,
            "description": self.description,
            "categories": [c.value for c in self.categories],
            "start_date": self.start_date,
            "end_date": self.end_date,
            "active": self.active,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "case_number": self.case_number,
        }


@dataclass
class RetentionJob:
    """A retention job execution."""
    job_id: str
    policy_id: str
    action: RetentionAction
    
    # Results
    files_processed: int = 0
    files_archived: int = 0
    files_purged: int = 0
    bytes_processed: int = 0
    bytes_freed: int = 0
    
    # Timing
    started_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    
    # Status
    status: str = "running"
    error: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "policy_id": self.policy_id,
            "action": self.action.value,
            "files_processed": self.files_processed,
            "files_archived": self.files_archived,
            "files_purged": self.files_purged,
            "bytes_processed": self.bytes_processed,
            "bytes_freed": self.bytes_freed,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "status": self.status,
            "error": self.error,
        }


class DataRetentionManager:
    """
    Manages data retention for compliance.
    
    Features:
    - Configurable retention policies
    - Automatic archival and purging
    - Legal hold support
    - Compliance reporting
    """
    
    def __init__(self, data_dir: str = "data"):
        self.logger = get_logger("compliance.retention")
        self.data_dir = Path(data_dir)
        self.archive_dir = self.data_dir / "archive"
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        
        # Policies
        self._policies: Dict[str, RetentionPolicy] = {}
        self._init_default_policies()
        
        # Legal holds
        self._legal_holds: Dict[str, LegalHold] = {}
        
        # Job history
        self._jobs: List[RetentionJob] = []
        
        # Category to directory mapping
        self._category_dirs: Dict[RetentionCategory, str] = {
            RetentionCategory.TRANSACTIONS: "transactions",
            RetentionCategory.AUDIT_LOGS: "audit",
            RetentionCategory.TRADE_DATA: "trades",
            RetentionCategory.MARKET_DATA: "market_data",
            RetentionCategory.USER_DATA: "users",
            RetentionCategory.SYSTEM_LOGS: "logs",
            RetentionCategory.REPORTS: "reports",
        }
    
    def _init_default_policies(self) -> None:
        """Initialize default retention policies."""
        # Financial transactions - 7 years
        self._policies["transactions"] = RetentionPolicy(
            policy_id="transactions",
            category=RetentionCategory.TRANSACTIONS,
            name="Financial Transactions",
            hot_retention_days=90,
            warm_retention_days=365,
            cold_retention_days=2555,
            archive_after_days=90,
            purge_after_days=2555,
            regulatory_requirement="SEC Rule 17a-4, IRS requirements",
            minimum_retention_days=2555,
        )
        
        # Audit logs - 7 years
        self._policies["audit_logs"] = RetentionPolicy(
            policy_id="audit_logs",
            category=RetentionCategory.AUDIT_LOGS,
            name="Audit Logs",
            hot_retention_days=30,
            warm_retention_days=365,
            cold_retention_days=2555,
            archive_after_days=30,
            purge_after_days=2555,
            regulatory_requirement="SOX compliance",
            minimum_retention_days=2555,
        )
        
        # Market data - 1 year
        self._policies["market_data"] = RetentionPolicy(
            policy_id="market_data",
            category=RetentionCategory.MARKET_DATA,
            name="Market Data",
            hot_retention_days=7,
            warm_retention_days=90,
            cold_retention_days=365,
            archive_after_days=7,
            purge_after_days=365,
            regulatory_requirement="None",
            minimum_retention_days=30,
        )
        
        # System logs - 90 days
        self._policies["system_logs"] = RetentionPolicy(
            policy_id="system_logs",
            category=RetentionCategory.SYSTEM_LOGS,
            name="System Logs",
            hot_retention_days=7,
            warm_retention_days=30,
            cold_retention_days=90,
            archive_after_days=7,
            purge_after_days=90,
            regulatory_requirement="None",
            minimum_retention_days=30,
        )
    
    def add_policy(self, policy: RetentionPolicy) -> None:
        """Add a retention policy."""
        self._policies[policy.policy_id] = policy
        self.logger.info(f"Added retention policy: {policy.name}")
    
    def create_legal_hold(
        self,
        name: str,
        description: str,
        categories: List[RetentionCategory],
        start_date: Optional[float] = None,
        end_date: Optional[float] = None,
        case_number: str = "",
        created_by: str = "system",
    ) -> str:
        """Create a legal hold."""
        import uuid
        
        hold_id = f"hold_{uuid.uuid4().hex[:8]}"
        
        hold = LegalHold(
            hold_id=hold_id,
            name=name,
            description=description,
            categories=categories,
            start_date=start_date,
            end_date=end_date,
            case_number=case_number,
            created_by=created_by,
        )
        
        self._legal_holds[hold_id] = hold
        self.logger.warning(f"Legal hold created: {hold_id} - {name}")
        
        return hold_id
    
    def release_legal_hold(self, hold_id: str) -> bool:
        """Release a legal hold."""
        hold = self._legal_holds.get(hold_id)
        if not hold:
            return False
        
        hold.active = False
        self.logger.warning(f"Legal hold released: {hold_id}")
        return True
    
    def is_under_legal_hold(self, category: RetentionCategory, timestamp: float) -> bool:
        """Check if data is under legal hold."""
        for hold in self._legal_holds.values():
            if not hold.active:
                continue
            if category not in hold.categories:
                continue
            if hold.start_date and timestamp < hold.start_date:
                continue
            if hold.end_date and timestamp > hold.end_date:
                continue
            return True
        return False
    
    def run_retention(self, policy_id: Optional[str] = None) -> List[RetentionJob]:
        """Run retention policies."""
        import uuid
        
        jobs = []
        policies = [self._policies[policy_id]] if policy_id else list(self._policies.values())
        
        for policy in policies:
            if not policy.enabled:
                continue
            
            job = RetentionJob(
                job_id=f"job_{uuid.uuid4().hex[:8]}",
                policy_id=policy.policy_id,
                action=RetentionAction.ARCHIVE,
            )
            
            try:
                # Get data directory
                data_subdir = self._category_dirs.get(policy.category, "")
                if not data_subdir:
                    continue
                
                source_dir = self.data_dir / data_subdir
                if not source_dir.exists():
                    continue
                
                now = time.time()
                archive_cutoff = now - (policy.archive_after_days * 86400)
                purge_cutoff = now - (policy.purge_after_days * 86400)
                
                # Process files
                for file_path in source_dir.glob("**/*"):
                    if not file_path.is_file():
                        continue
                    
                    file_mtime = file_path.stat().st_mtime
                    file_size = file_path.stat().st_size
                    job.files_processed += 1
                    job.bytes_processed += file_size
                    
                    # Check legal hold
                    if self.is_under_legal_hold(policy.category, file_mtime):
                        continue
                    
                    # Purge old files
                    if file_mtime < purge_cutoff:
                        if file_mtime >= now - (policy.minimum_retention_days * 86400):
                            continue  # Don't purge before minimum retention
                        
                        file_path.unlink()
                        job.files_purged += 1
                        job.bytes_freed += file_size
                    
                    # Archive files
                    elif file_mtime < archive_cutoff:
                        self._archive_file(file_path, policy.category)
                        job.files_archived += 1
                
                job.status = "completed"
                policy.last_run = time.time()
                
            except Exception as e:
                job.status = "failed"
                job.error = str(e)
                self.logger.error(f"Retention job failed: {e}")
            
            job.completed_at = time.time()
            jobs.append(job)
            self._jobs.append(job)
        
        return jobs
    
    def _archive_file(self, file_path: Path, category: RetentionCategory) -> None:
        """Archive a file with compression."""
        # Create archive path
        rel_path = file_path.relative_to(self.data_dir)
        archive_path = self.archive_dir / f"{rel_path}.gz"
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Compress and move
        with open(file_path, "rb") as f_in:
            with gzip.open(archive_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
        
        # Remove original
        file_path.unlink()
    
    def restore_from_archive(self, archive_path: str) -> Optional[str]:
        """Restore a file from archive."""
        archive_file = Path(archive_path)
        if not archive_file.exists():
            return None
        
        # Determine restore path
        restore_path = self.data_dir / archive_file.relative_to(self.archive_dir).with_suffix("")
        restore_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Decompress
        with gzip.open(archive_file, "rb") as f_in:
            with open(restore_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
        
        self.logger.info(f"Restored from archive: {restore_path}")
        return str(restore_path)
    
    def get_storage_stats(self) -> Dict[str, Any]:
        """Get storage statistics."""
        stats = {
            "active_storage": {},
            "archive_storage": {},
            "total_active_bytes": 0,
            "total_archive_bytes": 0,
        }
        
        # Active storage
        for category, subdir in self._category_dirs.items():
            dir_path = self.data_dir / subdir
            if dir_path.exists():
                size = sum(f.stat().st_size for f in dir_path.glob("**/*") if f.is_file())
                stats["active_storage"][category.value] = size
                stats["total_active_bytes"] += size
        
        # Archive storage
        if self.archive_dir.exists():
            for category, subdir in self._category_dirs.items():
                archive_subdir = self.archive_dir / subdir
                if archive_subdir.exists():
                    size = sum(f.stat().st_size for f in archive_subdir.glob("**/*") if f.is_file())
                    stats["archive_storage"][category.value] = size
                    stats["total_archive_bytes"] += size
        
        return stats
    
    def get_compliance_report(self) -> Dict[str, Any]:
        """Generate compliance report for retention."""
        report = {
            "generated_at": time.time(),
            "policies": [],
            "legal_holds": [],
            "storage_stats": self.get_storage_stats(),
            "recent_jobs": [j.to_dict() for j in self._jobs[-10:]],
        }
        
        for policy in self._policies.values():
            policy_status = {
                **policy.to_dict(),
                "compliant": policy.purge_after_days >= policy.minimum_retention_days,
            }
            report["policies"].append(policy_status)
        
        for hold in self._legal_holds.values():
            report["legal_holds"].append(hold.to_dict())
        
        return report
    
    def get_status(self) -> Dict[str, Any]:
        """Get retention manager status."""
        return {
            "policies_count": len(self._policies),
            "active_legal_holds": sum(1 for h in self._legal_holds.values() if h.active),
            "total_jobs": len(self._jobs),
            "storage": self.get_storage_stats(),
            "policies": [p.to_dict() for p in self._policies.values()],
            "legal_holds": [h.to_dict() for h in self._legal_holds.values()],
        }


# Singleton
_retention_manager: Optional[DataRetentionManager] = None
_retention_manager_lock = threading.Lock()


def get_retention_manager() -> DataRetentionManager:
    """Get or create the Data Retention Manager singleton."""
    global _retention_manager
    if _retention_manager is None:
        with _retention_manager_lock:
            if _retention_manager is None:
                _retention_manager = DataRetentionManager()
    return _retention_manager
