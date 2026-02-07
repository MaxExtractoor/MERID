"""Utility script used by MERID RAG agents to list knowledge files.

The coverage analyzer flagged this file previously because it contained a BOM and
was missing a proper module guard. This rewrite removes the BOM, documents the
behavior, and provides a small helper API that can be imported in tests.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List


def scan_knowledge_directory(directory: str) -> Dict[str, object]:
    """Return a structured summary of .txt files in a knowledge directory."""
    dir_path = Path(directory)
    result: Dict[str, object] = {
        "directory": str(dir_path),
        "files_found": [],
        "content": "",
        "status": "processing",
        "message": "",
    }

    if not dir_path.exists():
        result["status"] = "error"
        result["message"] = "Knowledge directory not found"
        return result

    txt_files: List[Path] = sorted(dir_path.glob("*.txt"))
    result["files_found"] = [file.name for file in txt_files]

    if not txt_files:
        result["status"] = "empty"
        result["message"] = "No .txt files found"
        return result

    content_blocks: List[str] = []
    for file_path in txt_files:
        try:
            content = file_path.read_text(encoding="utf-8").strip()
            content_blocks.append(f"=== {file_path.name} ===\n{content}")
        except UnicodeDecodeError as exc:
            content_blocks.append(f"ERROR reading {file_path.name}: {exc}")

    result["content"] = "\n\n".join(content_blocks)
    result["status"] = "success"
    result["message"] = f"Loaded {len(txt_files)} file(s)"
    return result


def main() -> None:
    """CLI entry point used by the agent runtime."""
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        print(json.dumps({"error": "No input received"}))
        return

    try:
        params = json.loads(raw_input)
    except json.JSONDecodeError:
        print(json.dumps({"error": "Invalid JSON input"}))
        return

    directory = params.get("directory", r"C:\Dev\MERID\knowledge")
    query = params.get("query", "")

    result = scan_knowledge_directory(directory)
    result["query"] = query
    print(json.dumps(result))


if __name__ == "__main__":
    main()
