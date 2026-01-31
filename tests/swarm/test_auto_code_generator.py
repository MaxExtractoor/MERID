"""Tests for swarm.auto_code_generator."""

from __future__ import annotations

from textwrap import dedent

from swarm.auto_code_generator import AutoCodeGenerator, CodeSpec


def make_spec() -> CodeSpec:
    return CodeSpec(
        module_name="test_module",
        description="Test module",
        entities=[
            {"name": "TestEntity", "fields": "id: int, name: str"},
            {"name": "EmptyEntity", "fields": ""},
        ],
        endpoints=[
            {"path": "/health", "method": "GET", "name": "health", "description": "Health check"},
            {"path": "/", "method": "POST", "description": "Root"},
        ],
    )


def test_generate_returns_both_artifacts():
    generator = AutoCodeGenerator()
    artifacts = generator.generate(make_spec())

    assert set(artifacts.keys()) == {"module", "api"}
    assert "class TestEntity" in artifacts["module"]
    assert "@dataclass" in artifacts["module"]
    assert "router = APIRouter()" in artifacts["api"]


def test_render_module_contains_fields():
    generator = AutoCodeGenerator()
    module_code = generator._render_module(make_spec())

    assert '"""Generated module: Test module"""' in module_code
    assert "class TestEntity" in module_code
    assert "id: int" in module_code
    assert "name: str" in module_code
    assert "class EmptyEntity" in module_code


def test_render_api_creates_handlers():
    generator = AutoCodeGenerator()
    api_code = generator._render_api(make_spec())

    expected = dedent(
        '''
        @router.get("/health")
        async def health():
            """Health check"""
            return {"status": "ok"}
        '''
    ).strip()
    assert expected in api_code

    assert "@router.post(\"/\")" in api_code
    assert "async def root()" in api_code
