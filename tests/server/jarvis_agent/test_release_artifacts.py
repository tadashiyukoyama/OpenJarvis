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
    assert "location ^~ /.well-known/acme-challenge/" in config
    assert "root /www/sites/openjarvis/acme;" in config
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


def test_windows_edge_task_tracks_the_hidden_worker_process() -> None:
    manager = _text("scripts/edge/Manage-OpenJarvisEdgeTask.ps1")
    launcher = _text("scripts/edge/Start-OpenJarvisEdge.ps1")

    assert "System32\\WindowsPowerShell\\v1.0\\powershell.exe" in manager
    assert "-WindowStyle Hidden" in manager
    assert '-Repository `"$Repository`"' in manager
    assert "Start-Process -FilePath $python" in launcher
    assert "-WindowStyle Hidden -Wait -PassThru" in launcher
    assert "exit $process.ExitCode" in launcher


def test_windows_shared_codex_runtime_is_explicit_versioned_and_fail_safe() -> None:
    module = _text("scripts/edge/SharedCodexRuntime.psm1")
    protocol = _text("scripts/edge/SharedCodexProtocol.psm1")
    manager = _text("scripts/edge/Manage-OpenJarvisSharedCodexTask.ps1")
    server = _text("scripts/edge/Start-OpenJarvisSharedCodex.ps1")
    desktop = _text("scripts/edge/Start-OpenJarvisCodexDesktop.ps1")
    shortcut = _text("scripts/edge/start-openjarvis-codex.cmd")
    smoke = _text("tests/windows/Invoke-SharedCodexProtocolSmoke.ps1")
    runbook = _text("docs/project/operations/JARVIS-SHARED-CODEX-RUNTIME.md")

    assert "Resolve-OpenJarvisCodexRuntime" in module
    assert "OpenAI\\Codex\\bin" in module
    assert module.count("Get-OpenJarvisFileSha256") >= 5
    assert "Matches: $($matches.Count)" in module
    assert "CurrentRuntime = $currentRuntime" in module
    assert "AllowUnsharedDesktopRecovery" in module
    assert 'ReadyUrl = "http://127.0.0.1:$Port/readyz"' in module
    assert 'HealthUrl = "http://127.0.0.1:$Port/healthz"' in module
    assert "ProtocolInitialized" in module
    assert "Get-OpenJarvisDesktopCodexTopology" in module
    assert "PrivateAppServerCount" in module
    assert "initialize" in protocol
    assert "initialized" in protocol
    assert "MaximumBytes = 1048576" in protocol
    assert "ClientWebSocket" in protocol

    assert "ValidateSet('Status', 'Validate', 'RemoveLegacy')" in manager
    assert "shared-codex-user-environment.backup.json" in manager
    assert "Restore-OpenJarvisLegacyUserEnvironment" in manager
    assert "New-ScheduledTaskTrigger" not in manager
    assert "Register-ScheduledTask" not in manager
    assert "'Install'" not in manager
    assert "'Start'" not in manager

    assert "[string]$ApprovalPolicy = 'on-request'" in server
    assert "[string]$SandboxMode = 'workspace-write'" in server
    assert "app-server', '--listen', $config.SharedUrl" in server
    assert "Start-Process -FilePath $config.CodexExe" in server
    assert "Wait-OpenJarvisSharedCodexReadiness" in server
    assert "VALIDATED_WITHOUT_START" in server
    assert "'User'" not in server and "'Machine'" not in server

    assert "Start-Process -FilePath $config.DesktopExe" in desktop
    assert "CODEX_APP_SERVER_WS_URL', $config.SharedUrl, 'Process'" in desktop
    assert "NORMAL_CODEX_STARTED_WITHOUT_REDIRECT" in desktop
    assert "NORMAL_CODEX_RECOVERED_AFTER_SHARED_JOIN_FAILURE" in desktop
    assert "Normal fallback was withheld" in desktop
    assert "Codex Desktop is already open in normal/private mode" in desktop
    assert "Stop-Process" not in desktop
    assert "'User'" not in desktop and "'Machine'" not in desktop
    assert "WindowStyle Hidden" not in shortcut

    assert "[int]$Port = 18131" in smoke
    assert "ThreadOrTurnSent = $false" in smoke
    assert "StaleRuntimeRejected" in smoke
    assert "Test-OpenJarvisSharedCodexProtocol" in smoke
    assert "Refusing to remove unsafe path" in smoke

    assert "opt-in" in runbook
    assert "never writes `CODEX_APP_SERVER_WS_URL` at User or Machine scope" in runbook
    assert "experimental" in runbook
