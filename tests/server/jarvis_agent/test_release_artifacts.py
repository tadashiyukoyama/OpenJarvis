from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_vps_container_is_pinned_minimal_and_fail_closed() -> None:
    dockerfile = _text("deploy/vps/Dockerfile")
    compose = _text("deploy/vps/compose.yaml")

    assert dockerfile.count("@sha256:") >= 2
    assert "USER 10001:10001" in dockerfile
    assert '"--workers", "1"' in dockerfile
    assert "healthz" in dockerfile
    assert "ollama" not in dockerfile.lower()
    assert "8131" not in dockerfile
    install_step = dockerfile.index("RUN uv pip install --system --no-deps .")
    for required_copy in (
        "COPY scripts/install/ ./scripts/install/",
        "COPY deploy/windows/ ./deploy/windows/",
    ):
        assert required_copy in dockerfile
        assert dockerfile.index(required_copy) < install_step
    assert 'OPENJARVIS_EXTERNAL_MUTATIONS_ENABLED: "false"' in compose
    assert '"127.0.0.1:${OPENJARVIS_CORE_PORT:-8180}:8000"' in compose
    assert "read_only: true" in compose
    assert "cap_drop:" in compose and "- ALL" in compose
    assert "no-new-privileges:true" in compose
    assert "./private/core.env" in compose


def test_openresty_exposes_only_explicit_public_boundaries() -> None:
    config = _text("deploy/vps/openresty-openjarvis.conf.example")

    assert config.count("access_log off;") >= 4
    assert "location = /edge" in config
    assert "proxy_set_header Upgrade $http_upgrade" in config
    assert "location = /v1/jarvis/agent/providers/acelerachat/webhooks" in config
    assert "location ^~ /local-agent/v1/jarvis/agent/" in config
    assert "proxy_set_header X-OpenJarvis-MCP-Gateway 1" in config
    assert "location = /health {" in config
    assert "workbox-[a-z0-9]+\\.js" in config
    assert "location / {" in config and "return 404;" in config
    assert "proxy_pass http://127.0.0.1:8131" not in config


def test_release_examples_contain_placeholders_not_active_secrets() -> None:
    examples = [
        _text("deploy/vps/core.env.example"),
        _text("deploy/windows/edge-worker.env.example"),
        _text("deploy/windows/agent-mcp.env.example"),
    ]

    for content in examples:
        assert "<private" in content
        assert "AQ." not in content
    assert "OPENJARVIS_EXTERNAL_MUTATIONS_ENABLED=false" in examples[0]
    assert "ws://127.0.0.1:8131" in examples[1]
    assert "/local-agent" in examples[1]
    assert r"\\.\pipe\openjarvis-agent-mcp" in examples[1]
    assert r"\\.\pipe\openjarvis-agent-mcp" in examples[2]


def test_release_context_excludes_private_and_local_artifacts() -> None:
    dockerignore = _text(".dockerignore")

    for excluded in (
        ".git",
        ".manus-audit",
        ".private",
        ".venv",
        "**/node_modules",
        "deploy/vps/private",
        "*.sqlite3",
    ):
        assert excluded in dockerignore
