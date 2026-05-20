"""Hedge Fill Persistence & Recovery (Task 8)

Handles saving and loading hedge fills for recovery after restarts.
Key functions:
- save_hedge_fills(): Persist hedge fills to disk
- load_hedge_fills(): Restore hedge fills after restart
- recover_hedge_pnl_tracker(): Restore PnL tracker state
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any
import logging

logger = logging.getLogger(__name__)

# Default persistence directory
# Task 8 Fix: Configurable via environment variable for containerized deployments
PERSISTENCE_DIR = Path(os.environ.get("MERID_HEDGE_DATA_DIR", Path.home() / ".merid" / "hedge_data"))
HEDGE_FILLS_FILE = "hedge_fills.json"
PNL_TRACKER_FILE = "hedge_pnl_state.json"


def _get_persistence_path(filename: str) -> Path:
    """Get full path for persistence file."""
    PERSISTENCE_DIR.mkdir(parents=True, exist_ok=True)
    return PERSISTENCE_DIR / filename


def save_hedge_fills(
    fills: List[Dict[str, Any]],
    filepath: Optional[str] = None,
) -> str:
    """Persist hedge fills to JSON file.
    
    Task 8: Enables recovery of hedge fills after system restart.
    
    Args:
        fills: List of hedge fill dictionaries with metadata
        filepath: Optional custom path (defaults to ~/.merid/hedge_data/hedge_fills.json)
        
    Returns:
        Path to saved file
    """
    path = Path(filepath) if filepath else _get_persistence_path(HEDGE_FILLS_FILE)
    
    data = {
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "fill_count": len(fills),
        "fills": fills,
    }
    
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)
    
    logger.info(
        "[HEDGE-PERSISTENCE] Saved %d hedge fills to %s",
        len(fills), path
    )
    
    return str(path)


def load_hedge_fills(
    filepath: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Load persisted hedge fills from JSON file.
    
    Task 8: Recovers hedge fills after system restart.
    
    Args:
        filepath: Optional custom path (defaults to ~/.merid/hedge_data/hedge_fills.json)
        
    Returns:
        List of hedge fill dictionaries (empty if no file or error)
    """
    path = Path(filepath) if filepath else _get_persistence_path(HEDGE_FILLS_FILE)
    
    if not path.exists():
        logger.debug("[HEDGE-PERSISTENCE] No hedge fills file found at %s", path)
        return []
    
    try:
        with open(path, 'r') as f:
            data = json.load(f)
        
        fills = data.get("fills", [])
        saved_at = data.get("saved_at", "unknown")
        
        logger.info(
            "[HEDGE-PERSISTENCE] Loaded %d hedge fills from %s (saved at %s)",
            len(fills), path, saved_at
        )
        
        return fills
    except Exception as exc:
        logger.error(
            "[HEDGE-PERSISTENCE] Failed to load hedge fills from %s: %s",
            path, exc
        )
        return []


def save_hedge_pnl_tracker(
    tracker_state: Dict[str, Any],
    filepath: Optional[str] = None,
) -> str:
    """Persist PnL tracker state to JSON file.
    
    Task 8: Enables recovery of hedge PnL calculations after restart.
    
    Args:
        tracker_state: Serialized tracker state from HedgePnLTracker.to_dict()
        filepath: Optional custom path (defaults to ~/.merid/hedge_data/hedge_pnl_state.json)
        
    Returns:
        Path to saved file
    """
    path = Path(filepath) if filepath else _get_persistence_path(PNL_TRACKER_FILE)
    
    data = {
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "tracker_state": tracker_state,
    }
    
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)
    
    record_count = len(tracker_state.get("records", []))
    logger.info(
        "[HEDGE-PERSISTENCE] Saved PnL tracker with %d records to %s",
        record_count, path
    )
    
    return str(path)


def load_hedge_pnl_tracker(
    filepath: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Load persisted PnL tracker state from JSON file.
    
    Task 8: Recovers hedge PnL state after system restart.
    
    Args:
        filepath: Optional custom path (defaults to ~/.merid/hedge_data/hedge_pnl_state.json)
        
    Returns:
        Tracker state dict or None if not found/error
    """
    path = Path(filepath) if filepath else _get_persistence_path(PNL_TRACKER_FILE)
    
    if not path.exists():
        logger.debug("[HEDGE-PERSISTENCE] No PnL tracker file found at %s", path)
        return None
    
    try:
        with open(path, 'r') as f:
            data = json.load(f)
        
        tracker_state = data.get("tracker_state", {})
        saved_at = data.get("saved_at", "unknown")
        record_count = len(tracker_state.get("records", []))
        
        logger.info(
            "[HEDGE-PERSISTENCE] Loaded PnL tracker with %d records from %s (saved at %s)",
            record_count, path, saved_at
        )
        
        return tracker_state
    except Exception as exc:
        logger.error(
            "[HEDGE-PERSISTENCE] Failed to load PnL tracker from %s: %s",
            path, exc
        )
        return None


def backup_hedge_data(
    backup_dir: Optional[str] = None,
) -> Dict[str, str]:
    """Create timestamped backup of all hedge data.
    
    Task 8: Enables rollback if recovery goes wrong.
    
    Args:
        backup_dir: Optional custom backup directory
        
    Returns:
        Dict with paths to backup files
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    
    if backup_dir:
        backup_path = Path(backup_dir) / timestamp
    else:
        backup_path = PERSISTENCE_DIR / "backups" / timestamp
    
    backup_path.mkdir(parents=True, exist_ok=True)
    
    files_backed = {}
    
    # Backup fills
    fills_path = _get_persistence_path(HEDGE_FILLS_FILE)
    if fills_path.exists():
        backup_file = backup_path / HEDGE_FILLS_FILE
        with open(fills_path, 'r') as src:
            with open(backup_file, 'w') as dst:
                dst.write(src.read())
        files_backed["fills"] = str(backup_file)
    
    # Backup PnL tracker
    pnl_path = _get_persistence_path(PNL_TRACKER_FILE)
    if pnl_path.exists():
        backup_file = backup_path / PNL_TRACKER_FILE
        with open(pnl_path, 'r') as src:
            with open(backup_file, 'w') as dst:
                dst.write(src.read())
        files_backed["pnl_tracker"] = str(backup_file)
    
    logger.info(
        "[HEDGE-PERSISTENCE] Created backup at %s with %d files",
        backup_path, len(files_backed)
    )
    
    return files_backed


def cleanup_old_backups(
    max_age_days: int = 7,
    backup_dir: Optional[str] = None,
) -> int:
    """Remove backup files older than specified age.
    
    Args:
        max_age_days: Maximum age in days
        backup_dir: Optional custom backup directory
        
    Returns:
        Number of directories removed
    """
    from datetime import timedelta
    
    if backup_dir:
        base_path = Path(backup_dir)
    else:
        base_path = PERSISTENCE_DIR / "backups"
    
    if not base_path.exists():
        return 0
    
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    removed = 0
    
    for item in base_path.iterdir():
        if item.is_dir():
            try:
                # Parse timestamp from directory name
                dir_time = datetime.strptime(item.name, "%Y%m%d_%H%M%S")
                dir_time = dir_time.replace(tzinfo=timezone.utc)
                
                if dir_time < cutoff:
                    import shutil
                    shutil.rmtree(item)
                    removed += 1
                    logger.debug(
                        "[HEDGE-PERSISTENCE] Removed old backup: %s",
                        item.name
                    )
            except ValueError:
                # Skip directories that don't match timestamp format
                continue
    
    if removed > 0:
        logger.info(
            "[HEDGE-PERSISTENCE] Cleaned up %d old backup directories",
            removed
        )
    
    return removed


class HedgePersistenceManager:
    """Manager for hedge fill persistence operations.
    
    Task 8: Provides automated save/restore with periodic persistence.
    """
    
    def __init__(self, auto_save_interval_cycles: int = 10):
        self._auto_save_interval = auto_save_interval_cycles
        self._cycle_count = 0
        self._last_saved_fills: int = 0
        self._last_saved_records: int = 0
    
    def maybe_auto_save(
        self,
        fills: List[Dict[str, Any]],
        tracker: Any,  # HedgePnLTracker
    ) -> bool:
        """Auto-save if enough cycles have passed or data has changed.
        
        Returns:
            True if save occurred
        """
        self._cycle_count += 1
        
        if self._cycle_count >= self._auto_save_interval:
            should_save = True
        else:
            # Check if data changed
            current_fills = len(fills)
            current_records = len(tracker._records) if hasattr(tracker, '_records') else 0
            should_save = (
                current_fills != self._last_saved_fills or
                current_records != self._last_saved_records
            )
        
        if should_save:
            self.save_all(fills, tracker)
            self._cycle_count = 0
            return True
        
        return False
    
    def save_all(
        self,
        fills: List[Dict[str, Any]],
        tracker: Any,  # HedgePnLTracker
    ) -> Dict[str, str]:
        """Save both fills and PnL tracker state.
        
        Returns:
            Dict with paths to saved files
        """
        # Update counts before saving
        self._last_saved_fills = len(fills)
        self._last_saved_records = len(tracker._records) if hasattr(tracker, '_records') else 0
        
        paths = {}
        
        # Save fills
        fills_path = save_hedge_fills(fills)
        paths["fills"] = fills_path
        
        # Save PnL tracker
        if hasattr(tracker, 'to_dict'):
            pnl_path = save_hedge_pnl_tracker(tracker.to_dict())
            paths["pnl_tracker"] = pnl_path
        
        logger.info(
            "[HEDGE-PERSISTENCE] Saved all hedge data: %d fills, %d PnL records",
            self._last_saved_fills, self._last_saved_records
        )
        
        return paths
    
    def load_all(
        self,
        tracker_class: Any,  # HedgePnLTracker class
    ) -> tuple:
        """Load both fills and PnL tracker state.
        
        Returns:
            Tuple of (fills_list, tracker_instance or None)
        """
        fills = load_hedge_fills()
        
        tracker_state = load_hedge_pnl_tracker()
        tracker = None
        
        if tracker_state and hasattr(tracker_class, 'from_dict'):
            tracker = tracker_class.from_dict(tracker_state)
        
        logger.info(
            "[HEDGE-PERSISTENCE] Loaded all hedge data: %d fills, tracker=%s",
            len(fills), "present" if tracker else "missing"
        )
        
        return fills, tracker
