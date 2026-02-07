from __future__ import annotations

import re
from pathlib import Path

FILES = [
    Path(r"c:/Dev/MERID/docs/polymarket_endpoints.md"),
    Path(r"c:/Dev/MERID/SYNTAX_SCAN_REPORT.md"),
    Path(r"c:/Dev/MERID/WEEK_N_ACTION_PLAN.md"),
]

LIST_PATTERNS = (
    "- ",
    "* ",
    "1. ",
    "2. ",
    "3. ",
)

REPLACEMENTS = (
    (re.compile(r"- \*\*(.+?)\*\*:"), r"- \1:"),
    (re.compile(r"\*\*(.+?)\*\*: " ), r"\1: "),
)


def ensure_blank_lines(lines: list[str], condition, before: bool) -> list[str]:
    i = 0
    while i < len(lines):
        if condition(lines[i]):
            if before:
                if i > 0 and lines[i - 1].strip() and not condition(lines[i - 1]):
                    lines.insert(i, "")
                    i += 1
            else:
                if i + 1 < len(lines):
                    if lines[i + 1].strip():
                        lines.insert(i + 1, "")
                else:
                    lines.append("")
        i += 1
    return lines


def is_heading(line: str) -> bool:
    stripped = line.lstrip()
    return stripped.startswith("#")


def is_fence(line: str) -> bool:
    return line.strip().startswith("```")


def is_list(line: str) -> bool:
    stripped = line.lstrip()
    return any(stripped.startswith(prefix) for prefix in LIST_PATTERNS)


def clean_file(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for pattern, replacement in REPLACEMENTS:
        text = pattern.sub(replacement, text)

    lines = text.replace("\r\n", "\n").split("\n")

    # ensure blank line before headings and code fences
    lines = ensure_blank_lines(lines, is_heading, before=True)
    lines = ensure_blank_lines(lines, is_heading, before=False)
    lines = ensure_blank_lines(lines, is_fence, before=True)
    lines = ensure_blank_lines(lines, is_fence, before=False)

    # ensure blank line before and after list blocks
    lines = ensure_blank_lines(lines, is_list, before=True)
    lines = ensure_blank_lines(lines, is_list, before=False)

    # collapse multiple blank lines
    cleaned: list[str] = []
    for line in lines:
        if line.strip() == "" and cleaned and cleaned[-1].strip() == "":
            continue
        cleaned.append(line)

    # ensure file ends with newline
    path.write_text("\n".join(cleaned).rstrip() + "\n", encoding="utf-8")


if __name__ == "__main__":
    for file_path in FILES:
        if file_path.exists():
            clean_file(file_path)
