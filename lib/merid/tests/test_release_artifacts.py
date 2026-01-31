import os
from pathlib import Path


def test_version_file_exists():
    p = Path(__file__).resolve().parents[1] / "VERSION"
    assert p.exists(), "VERSION file must exist for release automation"
    content = p.read_text().strip()
    assert content.startswith("v"), "Version should be semantic and start with 'v'"


def test_changelog_has_version():
    changelog = Path(__file__).resolve().parents[1] / "docs" / "CHANGELOG.md"
    text = changelog.read_text()
    assert "## v0.1.0 (2026-01-31)" in text, "CHANGELOG must contain v0.1.0 section"


def test_release_notes_present_and_references_changelog():
    rn = Path(__file__).resolve().parents[1] / "RELEASE_NOTES.md"
    assert rn.exists(), "RELEASE_NOTES.md should exist"
    txt = rn.read_text()
    assert "v0.1.0" in txt
    assert "Full changelog: see `docs/CHANGELOG.md`" in txt
