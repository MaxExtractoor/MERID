"""
Audit anchor tests (S2-03 hardening).

Validates:
- Merkle root computation (empty, single, even, odd leaf counts)
- Anchor creation and receipt structure
- Anchor verification (pass and fail)
- Tamper detection (modified entry invalidates anchor)
- InMemoryAnchorStore CRUD
- FileAnchorStore persistence roundtrip
- Multiple sequential anchors
"""

import json
import os
import shutil
import tempfile
import unittest

from core.audit_anchor import (
    AnchorReceipt,
    AuditAnchor,
    AuditEntry,
    FileAnchorStore,
    InMemoryAnchorStore,
    compute_merkle_root,
    _sha256,
)


def _make_entries(n: int) -> list:
    """Create n dummy audit entries with unique hashes."""
    return [
        AuditEntry(
            sequence=i,
            entry_hash=_sha256(f"entry-{i}"),
            event_type="test",
            timestamp=1000000.0 + i,
        )
        for i in range(n)
    ]


class TestMerkleRoot(unittest.TestCase):
    """Merkle root computation."""

    def test_empty_list(self):
        root = compute_merkle_root([])
        self.assertTrue(len(root) == 64)  # SHA-256 hex

    def test_single_hash(self):
        root = compute_merkle_root(["abc123"])
        self.assertTrue(len(root) == 64)

    def test_two_hashes(self):
        root = compute_merkle_root(["a", "b"])
        expected = _sha256("a" + "b")
        self.assertEqual(root, expected)

    def test_even_count(self):
        hashes = [_sha256(f"h{i}") for i in range(4)]
        root = compute_merkle_root(hashes)
        self.assertTrue(len(root) == 64)

    def test_odd_count_duplicates_last(self):
        hashes = [_sha256(f"h{i}") for i in range(3)]
        root = compute_merkle_root(hashes)
        self.assertTrue(len(root) == 64)

    def test_deterministic(self):
        hashes = [_sha256(f"h{i}") for i in range(5)]
        r1 = compute_merkle_root(hashes)
        r2 = compute_merkle_root(hashes)
        self.assertEqual(r1, r2)

    def test_different_inputs_different_roots(self):
        r1 = compute_merkle_root(["a", "b"])
        r2 = compute_merkle_root(["c", "d"])
        self.assertNotEqual(r1, r2)

    def test_large_set(self):
        hashes = [_sha256(f"entry-{i}") for i in range(1000)]
        root = compute_merkle_root(hashes)
        self.assertTrue(len(root) == 64)


class TestAuditAnchorCreation(unittest.TestCase):
    """Anchor creation and receipt structure."""

    def setUp(self):
        self.anchor = AuditAnchor(store=InMemoryAnchorStore())

    def test_anchor_returns_receipt(self):
        entries = _make_entries(10)
        receipt = self.anchor.anchor(entries)
        self.assertIsInstance(receipt, AnchorReceipt)

    def test_receipt_has_merkle_root(self):
        entries = _make_entries(5)
        receipt = self.anchor.anchor(entries)
        self.assertEqual(len(receipt.merkle_root), 64)

    def test_receipt_has_entry_count(self):
        entries = _make_entries(7)
        receipt = self.anchor.anchor(entries)
        self.assertEqual(receipt.entry_count, 7)

    def test_receipt_has_sequence_range(self):
        entries = _make_entries(10)
        receipt = self.anchor.anchor(entries)
        self.assertEqual(receipt.first_sequence, 0)
        self.assertEqual(receipt.last_sequence, 9)

    def test_receipt_has_timestamp(self):
        entries = _make_entries(3)
        receipt = self.anchor.anchor(entries)
        self.assertIn("T", receipt.timestamp)

    def test_receipt_to_dict(self):
        entries = _make_entries(3)
        receipt = self.anchor.anchor(entries)
        d = receipt.to_dict()
        self.assertIn("anchor_id", d)
        self.assertIn("merkle_root", d)

    def test_anchor_count_increments(self):
        self.anchor.anchor(_make_entries(5))
        self.anchor.anchor(_make_entries(5))
        self.assertEqual(self.anchor.anchor_count, 2)


class TestAnchorVerification(unittest.TestCase):
    """Anchor verification pass and fail."""

    def setUp(self):
        self.anchor = AuditAnchor(store=InMemoryAnchorStore())

    def test_verify_passes_with_same_entries(self):
        entries = _make_entries(10)
        receipt = self.anchor.anchor(entries)
        self.assertTrue(self.anchor.verify(receipt.anchor_id, entries))

    def test_verify_fails_with_modified_entry(self):
        entries = _make_entries(10)
        receipt = self.anchor.anchor(entries)
        # Tamper with one entry
        entries[5] = AuditEntry(sequence=5, entry_hash=_sha256("tampered"))
        self.assertFalse(self.anchor.verify(receipt.anchor_id, entries))

    def test_verify_fails_with_missing_entry(self):
        entries = _make_entries(10)
        receipt = self.anchor.anchor(entries)
        self.assertFalse(self.anchor.verify(receipt.anchor_id, entries[:9]))

    def test_verify_fails_with_extra_entry(self):
        entries = _make_entries(10)
        receipt = self.anchor.anchor(entries)
        entries.append(AuditEntry(sequence=10, entry_hash=_sha256("extra")))
        self.assertFalse(self.anchor.verify(receipt.anchor_id, entries))

    def test_verify_unknown_anchor_returns_false(self):
        entries = _make_entries(5)
        self.assertFalse(self.anchor.verify("nonexistent-id", entries))

    def test_verify_empty_entries_matches_empty_anchor(self):
        receipt = self.anchor.anchor([])
        self.assertTrue(self.anchor.verify(receipt.anchor_id, []))


class TestInMemoryAnchorStore(unittest.TestCase):
    """InMemoryAnchorStore CRUD."""

    def setUp(self):
        self.store = InMemoryAnchorStore()

    def test_store_type(self):
        self.assertEqual(self.store.store_type, "in_memory")

    def test_save_and_load(self):
        receipt = AnchorReceipt(
            anchor_id="test-1", merkle_root="abc", entry_count=5,
            first_sequence=0, last_sequence=4,
            timestamp="2026-02-07T00:00:00Z", store_type="in_memory",
        )
        self.store.save(receipt)
        loaded = self.store.load("test-1")
        self.assertEqual(loaded.merkle_root, "abc")

    def test_load_missing_returns_none(self):
        self.assertIsNone(self.store.load("missing"))

    def test_list_all(self):
        for i in range(3):
            self.store.save(AnchorReceipt(
                anchor_id=f"a-{i}", merkle_root="x", entry_count=1,
                first_sequence=0, last_sequence=0,
                timestamp="t", store_type="in_memory",
            ))
        self.assertEqual(len(self.store.list_all()), 3)


class TestFileAnchorStore(unittest.TestCase):
    """FileAnchorStore persistence roundtrip."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmpdir, "anchors.json")
        self.store = FileAnchorStore(self.path)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_store_type(self):
        self.assertEqual(self.store.store_type, "file")

    def test_save_creates_file(self):
        receipt = AnchorReceipt(
            anchor_id="f-1", merkle_root="abc", entry_count=5,
            first_sequence=0, last_sequence=4,
            timestamp="2026-02-07T00:00:00Z", store_type="file",
        )
        self.store.save(receipt)
        self.assertTrue(os.path.exists(self.path))

    def test_save_and_load_roundtrip(self):
        receipt = AnchorReceipt(
            anchor_id="f-2", merkle_root="def", entry_count=10,
            first_sequence=0, last_sequence=9,
            timestamp="2026-02-07T00:00:00Z", store_type="file",
        )
        self.store.save(receipt)
        # New store instance reads from same file
        store2 = FileAnchorStore(self.path)
        loaded = store2.load("f-2")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.merkle_root, "def")
        self.assertEqual(loaded.entry_count, 10)

    def test_list_all_persisted(self):
        for i in range(3):
            self.store.save(AnchorReceipt(
                anchor_id=f"f-{i}", merkle_root="x", entry_count=1,
                first_sequence=0, last_sequence=0,
                timestamp="t", store_type="file",
            ))
        store2 = FileAnchorStore(self.path)
        self.assertEqual(len(store2.list_all()), 3)

    def test_corrupted_file_returns_empty(self):
        with open(self.path, "w") as f:
            f.write("{bad json!!!")
        self.assertIsNone(self.store.load("anything"))
        self.assertEqual(self.store.list_all(), [])


class TestMultipleAnchors(unittest.TestCase):
    """Multiple sequential anchors."""

    def test_sequential_anchors_have_unique_ids(self):
        anchor = AuditAnchor(store=InMemoryAnchorStore())
        r1 = anchor.anchor(_make_entries(5))
        r2 = anchor.anchor(_make_entries(5))
        self.assertNotEqual(r1.anchor_id, r2.anchor_id)

    def test_list_anchors(self):
        anchor = AuditAnchor(store=InMemoryAnchorStore())
        anchor.anchor(_make_entries(5))
        anchor.anchor(_make_entries(10))
        anchors = anchor.list_anchors()
        self.assertEqual(len(anchors), 2)

    def test_different_entries_different_roots(self):
        anchor = AuditAnchor(store=InMemoryAnchorStore())
        r1 = anchor.anchor(_make_entries(5))
        r2 = anchor.anchor(_make_entries(10))
        self.assertNotEqual(r1.merkle_root, r2.merkle_root)


if __name__ == "__main__":
    unittest.main()
