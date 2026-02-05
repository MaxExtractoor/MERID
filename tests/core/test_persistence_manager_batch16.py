"""Tests for core persistence manager - Batch 16 Coverage."""
import pytest
from unittest.mock import MagicMock, patch, mock_open
import time
import json
import threading
from pathlib import Path

from core.persistence_manager import PersistenceManager


class TestPersistenceManager:
    """Tests for PersistenceManager."""

    @pytest.fixture
    def manager(self):
        """Create persistence manager."""
        return PersistenceManager(batch_size=5)

    def test_initialization(self, manager):
        """Test manager initialization."""
        assert manager.batch_size == 5

    def test_write_json(self, manager, tmp_path):
        """Test writing JSON data."""
        data = {"test": "data", "value": 123}
        test_file = tmp_path / "test.json"
        
        manager.write_json(test_file, data)
        manager.flush()
        
        # Verify file was written
        assert test_file.exists()
        with open(test_file) as f:
            loaded = json.load(f)
        assert loaded == data

    def test_read_json(self, manager, tmp_path):
        """Test reading JSON data."""
        data = {"test": "data"}
        test_file = tmp_path / "test.json"
        
        # Write directly
        with open(test_file, 'w') as f:
            json.dump(data, f)
        
        result = manager.read_json(test_file)
        assert result == data

    def test_read_json_missing(self, manager, tmp_path):
        """Test reading missing JSON file."""
        test_file = tmp_path / "missing.json"
        result = manager.read_json(test_file, default={"default": True})
        assert result == {"default": True}

    def test_batch_writes(self, manager, tmp_path):
        """Test batched write functionality."""
        test_file = tmp_path / "batched.json"
        
        # Write multiple times (should batch)
        for i in range(3):
            manager.write_json(test_file, {"count": i})
        
        # Data should be in queue, not file yet
        # Force flush
        manager.flush()
        
        with open(test_file) as f:
            data = json.load(f)
        assert data["count"] == 2  # Last write

    def test_get_stats(self, manager):
        """Test getting stats."""
        stats = manager.get_stats()
        assert "batch_size" in stats
        assert "batch_interval" in stats
        assert "compression_enabled" in stats


class TestPersistenceManagerRecovery:
    """Tests for PersistenceManager recovery features."""

    @pytest.fixture
    def manager(self):
        return PersistenceManager()

    def test_recover_from_backup_exists(self, manager, tmp_path):
        """Test recovery when backup exists."""
        test_file = tmp_path / "data.json"
        backup_file = tmp_path / "data.json.bak1"
        
        # Create backup file
        data = {"recovered": True}
        with open(backup_file, 'w') as f:
            json.dump(data, f)
        
        result = manager.recover_from_backup(test_file, backup_number=1)
        assert result is True
        assert test_file.exists()
        
        with open(test_file) as f:
            loaded = json.load(f)
        assert loaded == data

    def test_recover_from_backup_missing(self, manager, tmp_path):
        """Test recovery when backup doesn't exist."""
        test_file = tmp_path / "data.json"
        result = manager.recover_from_backup(test_file, backup_number=1)
        assert result is False


class TestPersistenceManagerConcurrency:
    """Tests for thread-safe operations."""

    @pytest.fixture
    def manager(self):
        return PersistenceManager()

    def test_concurrent_writes(self, manager, tmp_path):
        """Test concurrent write operations."""
        test_file = tmp_path / "concurrent.json"
        errors = []
        
        def writer(i):
            try:
                manager.write_json(test_file, {"thread": i})
            except Exception as e:
                errors.append(e)
        
        threads = [threading.Thread(target=writer, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(errors) == 0
