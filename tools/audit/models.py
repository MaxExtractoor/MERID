"""Shared dataclasses for the MERID bug audit framework."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class Severity(str, Enum):
    CRITICAL = "CRITICAL"   # production-impacting, fix immediately
    HIGH     = "HIGH"       # likely to surface under normal load
    MEDIUM   = "MEDIUM"     # surfaces under specific conditions
    LOW      = "LOW"        # theoretical / good hygiene


class Layer(str, Enum):
    FRONTEND = "frontend"
    BACKEND  = "backend"
    CROSS    = "cross-boundary"


@dataclass
class Finding:
    bug_type:    str            # e.g. "heisenbug"
    severity:    Severity
    layer:       Layer
    file:        str            # relative path
    line:        int
    column:      int = 0
    snippet:     str = ""       # the offending line(s)
    title:       str = ""       # short human label
    explanation: str = ""       # why this is a problem
    suggestion:  str = ""       # how to fix it

    def to_dict(self) -> dict:
        return {
            "bug_type":    self.bug_type,
            "severity":    self.severity.value,
            "layer":       self.layer.value,
            "file":        self.file,
            "line":        self.line,
            "column":      self.column,
            "snippet":     self.snippet.strip(),
            "title":       self.title,
            "explanation": self.explanation,
            "suggestion":  self.suggestion,
        }


SEVERITY_ORDER = {
    Severity.CRITICAL: 0,
    Severity.HIGH:     1,
    Severity.MEDIUM:   2,
    Severity.LOW:      3,
}
