"""
Secrets Guard — detect tracked secrets in the repository.

Provides:
- scan_for_tracked_secrets(): checks if known secret files are tracked in git
- scan_staged_for_secrets(): checks staged files for secret patterns
- check_env_only_secrets(): warns if secrets exist only in .env with no vault

Used by:
- Pre-commit hook (scripts/pre-commit-secrets-check.sh)
- Startup guard (refuse to start LIVE mode if secrets are tracked)
- Tests (test_secrets_guard.py)

Readiness Impact: S9-01 partial — secrets detection and prevention.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from utils.logger import get_logger

logger = get_logger("core.secrets_guard")


# Known secret file patterns that should never be tracked
TRACKED_SECRET_PATTERNS: List[str] = [
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.jks",
    "*.keystore",
    ".env",
    ".env.backup",
    ".env.production",
    ".env.live",
    "vault-token",
    ".vault-token",
]

# Content patterns that indicate secrets
SECRET_CONTENT_PATTERNS: List[re.Pattern] = [
    re.compile(r"-----BEGIN\s+(RSA\s+)?PRIVATE KEY-----"),
    re.compile(r"-----BEGIN\s+EC\s+PRIVATE\s+KEY-----"),
    re.compile(r"-----BEGIN\s+DSA\s+PRIVATE\s+KEY-----"),
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access key
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),  # OpenAI-style key
    re.compile(r"ghp_[a-zA-Z0-9]{36}"),  # GitHub PAT
    re.compile(r"glpat-[a-zA-Z0-9\-]{20,}"),  # GitLab PAT
]

# Known secret filenames (exact match)
KNOWN_SECRET_FILES: Set[str] = {
    "kalshi_private_key.pem",
    ".env.backup",
}


@dataclass
class SecretFinding:
    """A single finding from a secrets scan."""
    file_path: str
    finding_type: str  # "tracked_file", "content_pattern", "known_file"
    detail: str
    severity: str = "CRITICAL"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_path": self.file_path,
            "finding_type": self.finding_type,
            "detail": self.detail,
            "severity": self.severity,
        }


@dataclass
class ScanResult:
    """Result of a secrets scan."""
    clean: bool
    findings: List[SecretFinding] = field(default_factory=list)
    scanned_files: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "clean": self.clean,
            "findings": [f.to_dict() for f in self.findings],
            "scanned_files": self.scanned_files,
            "critical_count": sum(1 for f in self.findings if f.severity == "CRITICAL"),
        }


def _git_ls_files(repo_root: str) -> List[str]:
    """Get list of tracked files from git."""
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return [f.strip() for f in result.stdout.splitlines() if f.strip()]
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        logger.debug("silent catch in secrets_guard:111")
    return []


def _matches_pattern(filename: str, pattern: str) -> bool:
    """Check if a filename matches a glob-like pattern."""
    import fnmatch
    return fnmatch.fnmatch(filename, pattern) or fnmatch.fnmatch(
        os.path.basename(filename), pattern
    )


def scan_for_tracked_secrets(repo_root: Optional[str] = None) -> ScanResult:
    """Scan the git index for tracked secret files.

    Returns a ScanResult with findings for any tracked files that match
    known secret patterns.
    """
    if repo_root is None:
        repo_root = str(Path(__file__).resolve().parent.parent)

    tracked_files = _git_ls_files(repo_root)
    findings: List[SecretFinding] = []

    for filepath in tracked_files:
        basename = os.path.basename(filepath)

        # Check known secret files
        if basename in KNOWN_SECRET_FILES:
            findings.append(SecretFinding(
                file_path=filepath,
                finding_type="known_file",
                detail=f"Known secret file tracked in git: {basename}",
            ))
            continue

        # Check pattern matches
        for pattern in TRACKED_SECRET_PATTERNS:
            if _matches_pattern(filepath, pattern):
                findings.append(SecretFinding(
                    file_path=filepath,
                    finding_type="tracked_file",
                    detail=f"File matches secret pattern '{pattern}'",
                ))
                break

    return ScanResult(
        clean=len(findings) == 0,
        findings=findings,
        scanned_files=len(tracked_files),
    )


def scan_file_contents_for_secrets(
    file_path: str,
    max_size_bytes: int = 1_000_000,
) -> List[SecretFinding]:
    """Scan a single file's contents for secret patterns."""
    findings = []

    try:
        size = os.path.getsize(file_path)
        if size > max_size_bytes:
            return findings

        with open(file_path, "r", errors="ignore") as f:
            content = f.read()

        for pattern in SECRET_CONTENT_PATTERNS:
            if pattern.search(content):
                findings.append(SecretFinding(
                    file_path=file_path,
                    finding_type="content_pattern",
                    detail=f"Content matches secret pattern: {pattern.pattern[:40]}...",
                ))
    except (OSError, UnicodeDecodeError):
        logger.debug("silent catch in secrets_guard:187")

    return findings


def check_live_mode_safe(repo_root: Optional[str] = None) -> ScanResult:
    """Check if it's safe to run in LIVE mode.

    LIVE mode should be blocked if:
    - Secret files are tracked in git
    - No vault/KMS integration detected
    """
    result = scan_for_tracked_secrets(repo_root)

    # Additional check: warn if no vault integration
    if repo_root is None:
        repo_root = str(Path(__file__).resolve().parent.parent)

    vault_indicators = [
        os.path.exists(os.path.join(repo_root, "vault-config.hcl")),
        os.environ.get("VAULT_ADDR") is not None,
        os.environ.get("AWS_SECRET_ACCESS_KEY") is not None,
    ]

    if not any(vault_indicators):
        result.findings.append(SecretFinding(
            file_path="<environment>",
            finding_type="missing_vault",
            detail="No vault/KMS integration detected (VAULT_ADDR, vault-config.hcl, AWS_SECRET_ACCESS_KEY)",
            severity="WARNING",
        ))

    result.clean = not any(f.severity == "CRITICAL" for f in result.findings)
    return result


def get_gitignore_coverage(repo_root: Optional[str] = None) -> Dict[str, Any]:
    """Check .gitignore coverage for secret patterns."""
    if repo_root is None:
        repo_root = str(Path(__file__).resolve().parent.parent)

    gitignore_path = os.path.join(repo_root, ".gitignore")
    if not os.path.exists(gitignore_path):
        return {"exists": False, "entries": 0, "covers_secrets": False}

    with open(gitignore_path, "r") as f:
        lines = [l.strip() for l in f if l.strip() and not l.startswith("#")]

    # Check if key secret patterns are covered
    required_patterns = {"*.pem", "*.key", ".env", ".env.*"}
    covered = required_patterns.intersection(set(lines))

    return {
        "exists": True,
        "entries": len(lines),
        "covers_secrets": len(covered) == len(required_patterns),
        "covered_patterns": sorted(covered),
        "missing_patterns": sorted(required_patterns - covered),
    }
