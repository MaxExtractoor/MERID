"""
Automated code generation from specs.

Takes structured specifications and emits code artifacts (dataclasses, services,
FastAPI handlers) so Swarm Lab experiments can bootstrap prototypes quickly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass
class CodeSpec:
    module_name: str
    description: str
    entities: List[Dict[str, str]]
    endpoints: List[Dict[str, str]]


class AutoCodeGenerator:
    def generate(self, spec: CodeSpec) -> Dict[str, str]:
        return {
            "module": self._render_module(spec),
            "api": self._render_api(spec),
        }

    def _render_module(self, spec: CodeSpec) -> str:
        lines = [f'"""Generated module: {spec.description}"""', "", "from dataclasses import dataclass"]
        for entity in spec.entities:
            lines.append("")
            lines.append("@dataclass")
            lines.append(f"class {entity['name']}:")
            for field in entity.get("fields", "").split(","):
                field = field.strip()
                if field:
                    lines.append(f"    {field}")
        return "\n".join(lines)

    def _render_api(self, spec: CodeSpec) -> str:
        lines = ["from fastapi import APIRouter", "", "router = APIRouter()"]
        for endpoint in spec.endpoints:
            path = endpoint.get("path", "/")
            method = endpoint.get("method", "get").lower()
            handler_name = endpoint.get("name", path.strip("/").replace("/", "_") or "root")
            lines.append("")
            lines.append(f"@router.{method}(\"{path}\")")
            lines.append(f"async def {handler_name}():")
            lines.append(f"    \"\"\"{endpoint.get('description', 'Generated endpoint')}\"\"\"")
            lines.append("    return {\"status\": \"ok\"}")
        return "\n".join(lines)
