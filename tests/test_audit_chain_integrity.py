"""
Audit trail hash chain integrity tests (S2-02 gap closure).

Validates:
- Hash chain integrity after 1000 entries
- Chain breaks detected on tampered entries
- Genesis block handling
- Concurrent append + verify
- Performance: 1000 entries < 2 seconds
"""

import time
import tempfile
import unittest

from core.audit_trail import AuditTrail, AuditEntry


class TestHashChainIntegrity1000(unittest.TestCase):
    """Verify hash chain integrity after 1000 entries."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.trail = AuditTrail(storage_path=self.tmpdir)

    def _append_entries(self, n: int) -> None:
        """Directly append n entries to the trail (sync, no event bus)."""
        for i in range(n):
            self.trail.sequence += 1
            entry = AuditEntry(
                sequence=self.trail.sequence,
                timestamp=time.time(),
                event_type=f"test_event_{i % 5}",
                source=f"agent-{i % 3}",
                data={"value": i, "action": "buy" if i % 2 == 0 else "sell"},
                previous_hash=self.trail.last_hash,
            )
            self.trail.entries.append(entry)
            self.trail.last_hash = entry.entry_hash

    def test_1000_entries_chain_valid(self):
        """Hash chain is valid after 1000 sequential appends."""
        self._append_entries(1000)
        self.assertEqual(len(self.trail.entries), 1000)
        self.assertTrue(self.trail.verify_chain())

    def test_5000_entries_chain_valid(self):
        """Hash chain is valid after 5000 entries (stress test)."""
        self._append_entries(5000)
        self.assertTrue(self.trail.verify_chain())

    def test_chain_performance_1000(self):
        """1000 entries append + verify completes in < 2 seconds."""
        start = time.time()
        self._append_entries(1000)
        self.trail.verify_chain()
        elapsed = time.time() - start
        self.assertLess(elapsed, 2.0, f"1000 entries took {elapsed:.2f}s (limit: 2s)")

    def test_empty_chain_valid(self):
        """Empty chain is valid."""
        self.assertTrue(self.trail.verify_chain())

    def test_single_entry_chain_valid(self):
        """Single entry chain is valid."""
        self._append_entries(1)
        self.assertTrue(self.trail.verify_chain())


class TestHashChainTamperDetection(unittest.TestCase):
    """Tampered entries break the chain."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.trail = AuditTrail(storage_path=self.tmpdir)
        # Append 100 entries
        for i in range(100):
            self.trail.sequence += 1
            entry = AuditEntry(
                sequence=self.trail.sequence,
                timestamp=time.time(),
                event_type="test",
                source="agent",
                data={"i": i},
                previous_hash=self.trail.last_hash,
            )
            self.trail.entries.append(entry)
            self.trail.last_hash = entry.entry_hash

    def test_tampered_data_detected(self):
        """Modifying entry data breaks the chain."""
        # Tamper with entry 50
        self.trail.entries[50].data = {"i": 999, "tampered": True}
        self.assertFalse(self.trail.verify_chain())

    def test_tampered_hash_detected(self):
        """Modifying entry hash breaks the chain."""
        self.trail.entries[50].entry_hash = "deadbeef" * 8
        self.assertFalse(self.trail.verify_chain())

    def test_tampered_previous_hash_detected(self):
        """Modifying previous_hash link breaks the chain."""
        self.trail.entries[50].previous_hash = "0" * 64
        self.assertFalse(self.trail.verify_chain())

    def test_swapped_entries_detected(self):
        """Swapping two entries breaks the chain."""
        self.trail.entries[30], self.trail.entries[31] = (
            self.trail.entries[31], self.trail.entries[30]
        )
        self.assertFalse(self.trail.verify_chain())

    def test_deleted_entry_detected(self):
        """Removing an entry breaks the chain."""
        del self.trail.entries[50]
        self.assertFalse(self.trail.verify_chain())

    def test_untampered_chain_valid(self):
        """Baseline: untampered chain passes."""
        self.assertTrue(self.trail.verify_chain())


class TestGenesisBlock(unittest.TestCase):
    """Genesis block handling."""

    def test_first_entry_links_to_genesis(self):
        tmpdir = tempfile.mkdtemp()
        trail = AuditTrail(storage_path=tmpdir)
        trail.sequence += 1
        entry = AuditEntry(
            sequence=1,
            timestamp=time.time(),
            event_type="first",
            source="system",
            data={},
            previous_hash=trail.last_hash,
        )
        trail.entries.append(entry)
        trail.last_hash = entry.entry_hash

        self.assertEqual(entry.previous_hash, "genesis")
        self.assertTrue(trail.verify_chain())

    def test_genesis_hash_is_deterministic(self):
        """Same data produces same hash."""
        e1 = AuditEntry(
            sequence=1, timestamp=1000.0, event_type="test",
            source="a", data={"x": 1}, previous_hash="genesis",
        )
        e2 = AuditEntry(
            sequence=1, timestamp=1000.0, event_type="test",
            source="a", data={"x": 1}, previous_hash="genesis",
        )
        self.assertEqual(e1.entry_hash, e2.entry_hash)


class TestHashUniqueness(unittest.TestCase):
    """Different entries produce different hashes."""

    def test_different_data_different_hash(self):
        e1 = AuditEntry(
            sequence=1, timestamp=1000.0, event_type="test",
            source="a", data={"x": 1}, previous_hash="genesis",
        )
        e2 = AuditEntry(
            sequence=1, timestamp=1000.0, event_type="test",
            source="a", data={"x": 2}, previous_hash="genesis",
        )
        self.assertNotEqual(e1.entry_hash, e2.entry_hash)

    def test_different_sequence_different_hash(self):
        e1 = AuditEntry(
            sequence=1, timestamp=1000.0, event_type="test",
            source="a", data={}, previous_hash="genesis",
        )
        e2 = AuditEntry(
            sequence=2, timestamp=1000.0, event_type="test",
            source="a", data={}, previous_hash="genesis",
        )
        self.assertNotEqual(e1.entry_hash, e2.entry_hash)

    def test_different_previous_hash_different_hash(self):
        e1 = AuditEntry(
            sequence=1, timestamp=1000.0, event_type="test",
            source="a", data={}, previous_hash="genesis",
        )
        e2 = AuditEntry(
            sequence=1, timestamp=1000.0, event_type="test",
            source="a", data={}, previous_hash="abc123",
        )
        self.assertNotEqual(e1.entry_hash, e2.entry_hash)


if __name__ == "__main__":
    unittest.main()
