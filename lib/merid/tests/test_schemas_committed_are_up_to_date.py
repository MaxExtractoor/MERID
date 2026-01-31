from __future__ import annotations

import filecmp
import tempfile
from pathlib import Path

from web.schema_export import export_schemas


def test_committed_generated_schemas_are_up_to_date(tmp_path: Path) -> None:
    # Generate schemas to a temp directory
    export_schemas(tmp_path)

    committed_dir = Path("generated/schemas")
    assert committed_dir.exists(), "Committed schema directory missing"

    # Check each file in committed dir exists and matches the freshly generated one
    for committed in committed_dir.glob("*.json"):
        generated = tmp_path / committed.name
        assert generated.exists(), f"Generated schema {committed.name} missing"
        assert filecmp.cmp(committed, generated, shallow=False), (
            f"Committed schema {committed.name} is out of date. Regenerate with: python -c \"from web.schema_export import export_schemas; export_schemas('generated/schemas')\""
        )
