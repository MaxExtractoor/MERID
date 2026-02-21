"""
Tests for SecretsGuard (S9-01 partial: secrets detection and prevention).

Tests:
- Pattern matching for secret file names
- Content scanning for private keys and API keys
- .gitignore coverage check
- Live mode safety check
- ScanResult serialization
"""

import os
import tempfile
import unittest
from unittest.mock import patch

from core.secrets_guard import (
    SecretFinding,
    ScanResult,
    scan_for_tracked_secrets,
    scan_file_contents_for_secrets,
    check_live_mode_safe,
    get_gitignore_coverage,
    _matches_pattern,
    TRACKED_SECRET_PATTERNS,
    KNOWN_SECRET_FILES,
    SECRET_CONTENT_PATTERNS,
)


class TestPatternMatching(unittest.TestCase):
    """_matches_pattern correctly identifies secret file names."""

    def test_pem_pattern(self):
        self.assertTrue(_matches_pattern("kalshi_private_key.pem", "*.pem"))
        self.assertTrue(_matches_pattern("server.pem", "*.pem"))

    def test_key_pattern(self):
        self.assertTrue(_matches_pattern("private.key", "*.key"))

    def test_env_pattern(self):
        self.assertTrue(_matches_pattern(".env", ".env"))
        self.assertTrue(_matches_pattern(".env.backup", ".env.*"))
        self.assertTrue(_matches_pattern(".env.production", ".env.*"))

    def test_non_secret_file(self):
        self.assertFalse(_matches_pattern("main.py", "*.pem"))
        self.assertFalse(_matches_pattern("README.md", "*.key"))

    def test_nested_path(self):
        self.assertTrue(_matches_pattern("secrets/server.pem", "*.pem"))

    def test_known_secret_files(self):
        self.assertIn("kalshi_private_key.pem", KNOWN_SECRET_FILES)
        self.assertIn(".env.backup", KNOWN_SECRET_FILES)


class TestContentScanning(unittest.TestCase):
    """scan_file_contents_for_secrets detects secret content."""

    def test_detects_rsa_private_key(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAK...\n-----END RSA PRIVATE KEY-----\n")
            f.flush()
            findings = scan_file_contents_for_secrets(f.name)
        os.unlink(f.name)
        self.assertTrue(len(findings) > 0)
        self.assertEqual(findings[0].finding_type, "content_pattern")

    def test_detects_private_key_generic(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("-----BEGIN PRIVATE KEY-----\nMIIEvgIBADANBg...\n-----END PRIVATE KEY-----\n")
            f.flush()
            findings = scan_file_contents_for_secrets(f.name)
        os.unlink(f.name)
        self.assertTrue(len(findings) > 0)

    def test_detects_aws_access_key(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE\n")
            f.flush()
            findings = scan_file_contents_for_secrets(f.name)
        os.unlink(f.name)
        self.assertTrue(len(findings) > 0)

    def test_clean_file_no_findings(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("print('hello world')\n")
            f.flush()
            findings = scan_file_contents_for_secrets(f.name)
        os.unlink(f.name)
        self.assertEqual(len(findings), 0)

    def test_large_file_skipped(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("-----BEGIN PRIVATE KEY-----\n")
            f.flush()
            findings = scan_file_contents_for_secrets(f.name, max_size_bytes=5)
        os.unlink(f.name)
        self.assertEqual(len(findings), 0)

    def test_nonexistent_file_no_crash(self):
        findings = scan_file_contents_for_secrets("/nonexistent/path.txt")
        self.assertEqual(len(findings), 0)


class TestScanForTrackedSecrets(unittest.TestCase):
    """scan_for_tracked_secrets checks git index."""

    @patch("core.secrets_guard._git_ls_files")
    def test_clean_repo(self, mock_ls):
        mock_ls.return_value = ["main.py", "README.md", "core/engine.py"]
        result = scan_for_tracked_secrets("/fake/repo")
        self.assertTrue(result.clean)
        self.assertEqual(len(result.findings), 0)

    @patch("core.secrets_guard._git_ls_files")
    def test_tracked_pem_detected(self, mock_ls):
        mock_ls.return_value = ["main.py", "kalshi_private_key.pem"]
        result = scan_for_tracked_secrets("/fake/repo")
        self.assertFalse(result.clean)
        self.assertTrue(any("kalshi_private_key.pem" in f.file_path for f in result.findings))

    @patch("core.secrets_guard._git_ls_files")
    def test_tracked_env_backup_detected(self, mock_ls):
        mock_ls.return_value = ["main.py", ".env.backup"]
        result = scan_for_tracked_secrets("/fake/repo")
        self.assertFalse(result.clean)

    @patch("core.secrets_guard._git_ls_files")
    def test_tracked_key_file_detected(self, mock_ls):
        mock_ls.return_value = ["deploy/server.key"]
        result = scan_for_tracked_secrets("/fake/repo")
        self.assertFalse(result.clean)

    @patch("core.secrets_guard._git_ls_files")
    def test_scanned_files_count(self, mock_ls):
        mock_ls.return_value = ["a.py", "b.py", "c.py"]
        result = scan_for_tracked_secrets("/fake/repo")
        self.assertEqual(result.scanned_files, 3)


class TestCheckLiveModeSafe(unittest.TestCase):
    """check_live_mode_safe blocks LIVE if secrets tracked."""

    @patch("core.secrets_guard._git_ls_files")
    @patch.dict(os.environ, {}, clear=True)
    def test_clean_repo_no_vault_warns(self, mock_ls):
        mock_ls.return_value = ["main.py"]
        result = check_live_mode_safe("/fake/repo")
        # Clean (no CRITICAL), but has WARNING for missing vault
        self.assertTrue(result.clean)
        warnings = [f for f in result.findings if f.severity == "WARNING"]
        self.assertTrue(len(warnings) > 0)

    @patch("core.secrets_guard._git_ls_files")
    def test_tracked_secrets_blocks_live(self, mock_ls):
        mock_ls.return_value = ["main.py", "server.pem"]
        result = check_live_mode_safe("/fake/repo")
        self.assertFalse(result.clean)

    @patch("core.secrets_guard._git_ls_files")
    @patch.dict(os.environ, {"VAULT_ADDR": "http://vault:8200"})
    def test_vault_present_no_warning(self, mock_ls):
        mock_ls.return_value = ["main.py"]
        result = check_live_mode_safe("/fake/repo")
        self.assertTrue(result.clean)
        vault_warnings = [f for f in result.findings if "vault" in f.detail.lower()]
        self.assertEqual(len(vault_warnings), 0)


class TestGitignoreCoverage(unittest.TestCase):
    """get_gitignore_coverage checks .gitignore completeness."""

    def test_real_gitignore_exists(self):
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        result = get_gitignore_coverage(repo_root)
        self.assertTrue(result["exists"])
        self.assertGreater(result["entries"], 10)

    def test_real_gitignore_covers_secrets(self):
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        result = get_gitignore_coverage(repo_root)
        self.assertTrue(result["covers_secrets"])
        self.assertEqual(len(result["missing_patterns"]), 0)

    def test_missing_gitignore(self):
        result = get_gitignore_coverage("/nonexistent/path")
        self.assertFalse(result["exists"])


class TestScanResultSerialization(unittest.TestCase):
    """ScanResult and SecretFinding are JSON-serializable."""

    def test_finding_to_dict(self):
        f = SecretFinding("server.pem", "tracked_file", "matches *.pem")
        d = f.to_dict()
        self.assertEqual(d["file_path"], "server.pem")
        self.assertEqual(d["severity"], "CRITICAL")

    def test_scan_result_to_dict(self):
        result = ScanResult(
            clean=False,
            findings=[SecretFinding("x.pem", "tracked_file", "bad")],
            scanned_files=100,
        )
        d = result.to_dict()
        self.assertFalse(d["clean"])
        self.assertEqual(d["critical_count"], 1)
        self.assertEqual(d["scanned_files"], 100)

    def test_clean_result(self):
        result = ScanResult(clean=True, scanned_files=50)
        d = result.to_dict()
        self.assertTrue(d["clean"])
        self.assertEqual(d["critical_count"], 0)


class TestSecretContentPatterns(unittest.TestCase):
    """SECRET_CONTENT_PATTERNS cover common secret formats."""

    def test_patterns_count(self):
        self.assertGreaterEqual(len(SECRET_CONTENT_PATTERNS), 5)

    def test_rsa_key_pattern_matches(self):
        text = "-----BEGIN RSA PRIVATE KEY-----"
        self.assertTrue(any(p.search(text) for p in SECRET_CONTENT_PATTERNS))

    def test_ec_key_pattern_matches(self):
        text = "-----BEGIN EC PRIVATE KEY-----"
        self.assertTrue(any(p.search(text) for p in SECRET_CONTENT_PATTERNS))

    def test_aws_key_pattern_matches(self):
        text = "AKIAIOSFODNN7EXAMPLE"
        self.assertTrue(any(p.search(text) for p in SECRET_CONTENT_PATTERNS))

    def test_normal_text_no_match(self):
        text = "This is a normal Python file with no secrets."
        self.assertFalse(any(p.search(text) for p in SECRET_CONTENT_PATTERNS))


if __name__ == "__main__":
    unittest.main()
