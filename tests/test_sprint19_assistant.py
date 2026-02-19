"""Tests for Sprint 19 — Operator Assistant API + UI Wiring."""
import re
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB_REACT = ROOT / "web" / "react" / "src"
VIEWS_DIR = WEB_REACT / "views"
COMPONENTS_DIR = WEB_REACT / "components"
CONSTANTS_FILE = WEB_REACT / "config" / "constants.ts"
MAIN_PY = ROOT / "web" / "main.py"
ASSISTANT_API = ROOT / "web" / "api" / "assistant_api.py"


# ── 1. Backend API file exists and has correct structure ────────

class TestAssistantApiFile:
    """assistant_api.py exists with required endpoints and models."""

    def test_file_exists(self):
        assert ASSISTANT_API.exists(), "web/api/assistant_api.py not found"

    def test_has_query_endpoint(self):
        text = ASSISTANT_API.read_text(encoding="utf-8")
        assert "/query" in text
        assert "async def assistant_query" in text

    def test_has_contexts_endpoint(self):
        text = ASSISTANT_API.read_text(encoding="utf-8")
        assert "/contexts" in text
        assert "async def list_contexts" in text

    def test_has_request_model(self):
        text = ASSISTANT_API.read_text(encoding="utf-8")
        assert "class AssistantQuery" in text

    def test_has_response_model(self):
        text = ASSISTANT_API.read_text(encoding="utf-8")
        assert "class AssistantResponse" in text

    def test_has_message_model(self):
        text = ASSISTANT_API.read_text(encoding="utf-8")
        assert "class AssistantMessage" in text

    def test_records_governance_trace(self):
        text = ASSISTANT_API.read_text(encoding="utf-8")
        assert "record_trace" in text
        assert "get_llm_governance_store" in text

    def test_has_four_context_domains(self):
        text = ASSISTANT_API.read_text(encoding="utf-8")
        for domain in ["operator", "dev", "cognitive", "sports"]:
            assert f'"{domain}"' in text, f"Missing context domain: {domain}"

    def test_gathers_system_snapshot(self):
        text = ASSISTANT_API.read_text(encoding="utf-8")
        assert "_gather_system_snapshot" in text
        for section in ["portfolio", "risk", "pipeline_modes", "llm_governance", "dev_swarm"]:
            assert section in text, f"Missing snapshot section: {section}"


# ── 2. Backend wired into main.py ──────────────────────────────

class TestAssistantWiring:
    """Assistant router is imported and included in the FastAPI app."""

    def test_import_in_main(self):
        text = MAIN_PY.read_text(encoding="utf-8")
        assert "from web.api.assistant_api import router as assistant_router" in text

    def test_include_router_in_main(self):
        text = MAIN_PY.read_text(encoding="utf-8")
        assert "application.include_router(assistant_router)" in text


# ── 3. Frontend constants ──────────────────────────────────────

class TestAssistantConstants:
    """API_ENDPOINTS includes assistant keys."""

    def test_assistant_query_constant(self):
        text = CONSTANTS_FILE.read_text(encoding="utf-8")
        assert "ASSISTANT_QUERY" in text
        assert "/api/v1/assistant/query" in text

    def test_assistant_contexts_constant(self):
        text = CONSTANTS_FILE.read_text(encoding="utf-8")
        assert "ASSISTANT_CONTEXTS" in text
        assert "/api/v1/assistant/contexts" in text


# ── 4. AssistantPanel component ────────────────────────────────

class TestAssistantPanelComponent:
    """AssistantPanel.tsx exists with required features."""

    PANEL = COMPONENTS_DIR / "AssistantPanel.tsx"

    def test_file_exists(self):
        assert self.PANEL.exists(), "AssistantPanel.tsx not found"

    def test_imports_api_endpoints(self):
        text = self.PANEL.read_text(encoding="utf-8")
        assert "API_ENDPOINTS" in text

    def test_uses_assistant_query_endpoint(self):
        text = self.PANEL.read_text(encoding="utf-8")
        assert "API_ENDPOINTS.ASSISTANT_QUERY" in text

    def test_has_context_switching(self):
        text = self.PANEL.read_text(encoding="utf-8")
        for ctx in ["operator", "dev", "cognitive", "sports"]:
            assert ctx in text, f"Missing context: {ctx}"

    def test_has_message_rendering(self):
        text = self.PANEL.read_text(encoding="utf-8")
        assert "role: 'user'" in text or "role === 'user'" in text
        assert "role: 'assistant'" in text or "role === 'assistant'" in text

    def test_has_suggested_queries(self):
        text = self.PANEL.read_text(encoding="utf-8")
        assert "SUGGESTED_QUERIES" in text

    def test_has_loading_state(self):
        text = self.PANEL.read_text(encoding="utf-8")
        assert "loading" in text
        assert "Thinking" in text

    def test_has_trace_id_display(self):
        text = self.PANEL.read_text(encoding="utf-8")
        assert "traceId" in text

    def test_default_export(self):
        text = self.PANEL.read_text(encoding="utf-8")
        assert "export default function AssistantPanel" in text

    def test_no_hardcoded_fetch_urls(self):
        text = self.PANEL.read_text(encoding="utf-8")
        pattern = re.compile(r"""fetch\s*\(\s*['"]\/api""")
        assert not pattern.findall(text), "AssistantPanel has hardcoded fetch URLs"


# ── 5. Wired into DevSwarmControlCenter ────────────────────────

class TestDevSwarmAssistantTab:
    """DevSwarmControlCenter has an assistant tab."""

    DSC = VIEWS_DIR / "DevSwarmControlCenter.tsx"

    def test_imports_assistant_panel(self):
        text = self.DSC.read_text(encoding="utf-8")
        assert "import AssistantPanel" in text

    def test_has_assistant_tab(self):
        text = self.DSC.read_text(encoding="utf-8")
        assert "'assistant'" in text

    def test_renders_assistant_panel(self):
        text = self.DSC.read_text(encoding="utf-8")
        assert "<AssistantPanel" in text


# ── 6. Backend module imports correctly ────────────────────────

class TestAssistantModuleImport:
    """The assistant API module can be imported without errors."""

    def test_import_assistant_api(self):
        import web.api.assistant_api as mod
        assert hasattr(mod, "router")
        assert hasattr(mod, "assistant_query")
        assert hasattr(mod, "list_contexts")

    def test_assistant_query_model(self):
        from web.api.assistant_api import AssistantQuery
        q = AssistantQuery(query="test", context="operator")
        assert q.query == "test"
        assert q.context == "operator"
        assert q.include_system_snapshot is True

    def test_assistant_response_model(self):
        from web.api.assistant_api import AssistantResponse
        r = AssistantResponse(
            trace_id="ast-test",
            answer="test answer",
            context_domain="operator",
            latency_ms=10.0,
        )
        assert r.trace_id == "ast-test"
        assert r.answer == "test answer"

    def test_build_answer_portfolio(self):
        from web.api.assistant_api import _build_answer
        snapshot = {
            "portfolio": {
                "total_equity": 50000,
                "cash": 25000,
                "positions_count": 10,
                "domains": ["crypto", "prediction"],
            }
        }
        answer = _build_answer("What is my portfolio balance?", "operator", snapshot)
        assert "50,000" in answer
        assert "25,000" in answer

    def test_build_answer_fallback(self):
        from web.api.assistant_api import _build_answer
        answer = _build_answer("random question about nothing", "operator", {})
        assert "portfolio" in answer.lower() or "risk" in answer.lower()

    def test_context_prompts_exist(self):
        from web.api.assistant_api import _CONTEXT_PROMPTS
        assert "operator" in _CONTEXT_PROMPTS
        assert "dev" in _CONTEXT_PROMPTS
        assert "cognitive" in _CONTEXT_PROMPTS
        assert "sports" in _CONTEXT_PROMPTS
