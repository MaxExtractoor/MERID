from pathlib import Path


def test_publish_workflow_has_sbom_and_cosign():
    p = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "publish-on-tag.yml"
    text = p.read_text()
    assert "Generate SBOM" in text, "Publish workflow should generate an SBOM"
    assert "cosign" in text, "Publish workflow should include cosign signing steps (conditional on secrets)"
