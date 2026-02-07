from __future__ import annotations

import json
from pathlib import Path

from web.schema_export import export_schemas


def test_export_schemas(tmp_path: Path) -> None:
    export_schemas(tmp_path)
    for name in ("SubmitRequest", "MeridUpdate", "AuditEntry"):
        p = tmp_path / f"{name}.json"
        assert p.exists()
        data = json.loads(p.read_text(encoding="utf-8"))
        # Basic sanity checks
        assert isinstance(data, dict)
        assert ("title" in data) or ("$schema" in data) or ("properties" in data)
