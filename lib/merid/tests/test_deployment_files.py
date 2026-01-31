from __future__ import annotations

from pathlib import Path


def test_dockerfile_exists():
    p = Path("Dockerfile")
    assert p.exists()
    txt = p.read_text(encoding="utf-8")
    assert "FROM python" in txt


def test_docker_compose_exists():
    p = Path("docker-compose.yml")
    assert p.exists()
    txt = p.read_text(encoding="utf-8")
    assert "services" in txt and "web" in txt
