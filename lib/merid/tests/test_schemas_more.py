from __future__ import annotations

import pytest
from pydantic import ValidationError

from web.schemas import MeridUpdate, SubmitRequest


def test_merid_update_accepts_minimal_and_full() -> None:
    minimal = {"status": "started"}
    # Use the v2 style validator if available
    MeridUpdate.model_validate(minimal)

    full = {"status": "done", "energy": {"x": 1}, "progress": 100, "result": {"ok": True}}
    MeridUpdate.model_validate(full)


def test_merid_update_rejects_invalid_status() -> None:
    with pytest.raises(ValidationError):
        MeridUpdate.model_validate({"status": "unknown"})


def test_submit_request_rejects_empty() -> None:
    with pytest.raises(ValidationError):
        SubmitRequest(source="", payload="")
