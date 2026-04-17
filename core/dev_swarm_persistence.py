"""
Dev Swarm State Persistence

Simple JSON-based persistence for task history and state.
Designed for easy upgrade to database later.
"""

import json
import os
from typing import List, Optional, Dict, Any
from pathlib import Path
from datetime import datetime
import structlog

from core.dev_swarm import DevTask

logger = structlog.get_logger(__name__)


class DevSwarmPersistence:
    """Handles persistence of Dev Swarm tasks to disk."""
    
    def __init__(self, storage_path: str = "data/dev_swarm"):
        """
        Initialize persistence layer.
        
        Args:
            storage_path: Directory to store task data
        """
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.tasks_file = self.storage_path / "tasks.jsonl"
        self.metadata_file = self.storage_path / "metadata.json"
        
        logger.info("dev_swarm_persistence_initialized", path=str(self.storage_path))
    
    def save_task(self, task: DevTask) -> bool:
        """
        Save a single task to storage.
        
        Uses append-only JSONL format for durability.
        
        Args:
            task: DevTask to save
            
        Returns:
            True if successful, False otherwise
        """
        try:
            task_dict = self._task_to_dict(task)
            
            # Append to JSONL file
            with open(self.tasks_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(task_dict) + '\n')
            
            logger.debug("task_saved", task_id=task.task_id)
            return True
            
        except Exception as e:
            logger.error("task_save_failed", task_id=task.task_id, error=str(e))
            return False
    
    def load_tasks(self, limit: Optional[int] = None) -> List[DevTask]:
        """
        Load tasks from storage.
        
        Args:
            limit: Maximum number of tasks to load (most recent)
            
        Returns:
            List of DevTask objects
        """
        if not self.tasks_file.exists():
            logger.info("no_tasks_file", creating=True)
            return []
        
        try:
            tasks = []
            with open(self.tasks_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        task_dict = json.loads(line)
                        task = self._dict_to_task(task_dict)
                        tasks.append(task)
            
            # Return most recent tasks if limit specified
            if limit:
                tasks = tasks[-limit:]
            
            logger.info("tasks_loaded", count=len(tasks))
            return tasks
            
        except Exception as e:
            logger.error("task_load_failed", error=str(e))
            return []
    
    def get_task_by_id(self, task_id: str) -> Optional[DevTask]:
        """
        Get a specific task by ID.
        
        Args:
            task_id: Task ID to find
            
        Returns:
            DevTask if found, None otherwise
        """
        if not self.tasks_file.exists():
            return None
        
        try:
            # Read backwards for efficiency (recent tasks at end)
            with open(self.tasks_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            for line in reversed(lines):
                if line.strip():
                    task_dict = json.loads(line)
                    if task_dict.get('task_id') == task_id:
                        return self._dict_to_task(task_dict)
            
            return None
            
        except Exception as e:
            logger.error("task_get_failed", task_id=task_id, error=str(e))
            return None
    
    def update_task(self, task: DevTask) -> bool:
        """
        Update an existing task.
        
        Note: This rewrites the entire file. For production, use a database.
        
        Args:
            task: Updated task
            
        Returns:
            True if successful
        """
        try:
            tasks = self.load_tasks()
            
            # Find and replace task
            updated = False
            for i, t in enumerate(tasks):
                if t.task_id == task.task_id:
                    tasks[i] = task
                    updated = True
                    break
            
            # If not found, append
            if not updated:
                tasks.append(task)
            
            # Rewrite file
            with open(self.tasks_file, 'w', encoding='utf-8') as f:
                for t in tasks:
                    f.write(json.dumps(self._task_to_dict(t)) + '\n')
            
            logger.debug("task_updated", task_id=task.task_id)
            return True
            
        except Exception as e:
            logger.error("task_update_failed", task_id=task.task_id, error=str(e))
            return False
    
    def save_metadata(self, metadata: Dict[str, Any]) -> bool:
        """
        Save metadata (e.g., daily cost, last reset time).
        
        Args:
            metadata: Dictionary of metadata
            
        Returns:
            True if successful
        """
        try:
            with open(self.metadata_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2)
            
            logger.debug("metadata_saved")
            return True
            
        except Exception as e:
            logger.error("metadata_save_failed", error=str(e))
            return False
    
    def load_metadata(self) -> Dict[str, Any]:
        """
        Load metadata.
        
        Returns:
            Dictionary of metadata
        """
        if not self.metadata_file.exists():
            return {}
        
        try:
            with open(self.metadata_file, 'r', encoding='utf-8') as f:
                return json.load(f)
                
        except Exception as e:
            logger.error("metadata_load_failed", error=str(e))
            return {}
    
    def compact(self, keep_recent: int = 1000) -> bool:
        """Alias for compact_storage."""
        return self.compact_storage(keep_recent)

    def compact_storage(self, keep_recent: int = 1000) -> bool:
        """
        Compact storage by removing old tasks.
        
        Keeps only the most recent N tasks.
        
        Args:
            keep_recent: Number of recent tasks to keep
            
        Returns:
            True if successful
        """
        try:
            tasks = self.load_tasks()
            
            if len(tasks) <= keep_recent:
                logger.info("storage_already_compact", count=len(tasks))
                return True
            
            # Keep only recent tasks
            recent_tasks = tasks[-keep_recent:]
            
            # Create backup
            backup_file = self.storage_path / f"tasks_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
            if self.tasks_file.exists():
                import shutil
                shutil.copy2(self.tasks_file, backup_file)
            
            # Rewrite with recent tasks only
            with open(self.tasks_file, 'w', encoding='utf-8') as f:
                for task in recent_tasks:
                    f.write(json.dumps(self._task_to_dict(task)) + '\n')
            
            logger.info(
                "storage_compacted",
                removed=len(tasks) - keep_recent,
                kept=keep_recent,
                backup=str(backup_file)
            )
            return True
            
        except Exception as e:
            logger.error("storage_compact_failed", error=str(e))
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get storage statistics.
        
        Returns:
            Dictionary with storage stats
        """
        try:
            stats = {
                "storage_path": str(self.storage_path),
                "tasks_file_exists": self.tasks_file.exists(),
                "metadata_file_exists": self.metadata_file.exists(),
            }
            
            if self.tasks_file.exists():
                stats["tasks_file_size_bytes"] = self.tasks_file.stat().st_size
                stats["total_tasks"] = len(self.load_tasks())
            
            return stats
            
        except Exception as e:
            logger.error("storage_stats_failed", error=str(e))
            return {"error": str(e)}
    
    # Helper methods
    
    def _task_to_dict(self, task: DevTask) -> Dict[str, Any]:
        """Convert DevTask to dictionary for JSON serialization."""
        return {
            "task_id": task.task_id,
            "description": task.description,
            "target_files": task.target_files,
            "success_criteria": task.success_criteria,
            "priority": task.priority,
            "estimated_effort": task.estimated_effort,
            "timeout_seconds": task.timeout_seconds,
            "started_at": task.started_at,
            "completed_at": task.completed_at,
            "status": task.status,
            "error": task.error,
            "result": task.result,
        }
    
    def _dict_to_task(self, data: Dict[str, Any]) -> DevTask:
        """Convert dictionary to DevTask."""
        task = DevTask(
            description=data["description"],
            target_files=data["target_files"],
            success_criteria=data.get("success_criteria", ""),
            priority=data.get("priority", 1),
            estimated_effort=data.get("estimated_effort", "medium"),
            timeout_seconds=data.get("timeout_seconds"),
        )
        task.task_id = data["task_id"]
        task.status = data.get("status", "pending")
        task.started_at = data.get("started_at")
        task.completed_at = data.get("completed_at")
        task.error = data.get("error")
        task.result = data.get("result")
        return task
