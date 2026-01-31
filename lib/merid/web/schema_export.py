from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from web.schemas import SubmitRequest, MeridUpdate, AuditEntry


def iter_models() -> Iterable[tuple[str, type]]:
    yield "SubmitRequest", SubmitRequest
    yield "MeridUpdate", MeridUpdate
    yield "AuditEntry", AuditEntry


def export_schemas(output_dir: str | Path = "generated/schemas") -> None:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    for name, model in iter_models():
        # Support both Pydantic v1 and v2 schema introspection
        if hasattr(model, "model_json_schema"):
            schema = model.model_json_schema()
        else:
            schema = model.schema()

        path = out / f"{name}.json"
        path.write_text(json.dumps(schema, indent=2), encoding="utf-8")
