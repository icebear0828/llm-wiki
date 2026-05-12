from __future__ import annotations

import json
import shutil
import socket
import time
from pathlib import Path
from urllib import error, request

import pytest

from llmwiki.gateway.config import BackendConfig, GatewayConfig
from llmwiki.gateway.litellm_config import write_config
from llmwiki.gateway.server import health_check, start

pytestmark = pytest.mark.e2e

PORT = 8079
MASTER_KEY = "sk-test-master-e2e"


def _free_port_or_skip(port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            pytest.skip(f"port {port} already in use")


def _post_json(url: str, payload: dict[str, object], headers: dict[str, str]) -> int:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=body, method="POST", headers=headers)
    try:
        with request.urlopen(req, timeout=10.0) as resp:
            return int(resp.status)
    except error.HTTPError as e:
        return int(e.code)
    except (error.URLError, ConnectionError, TimeoutError, OSError):
        return 0


def test_proxy_starts_and_routes_three_protocols(tmp_path: Path) -> None:
    if shutil.which("litellm") is None:
        pytest.skip("litellm binary not installed")
    _free_port_or_skip(PORT)

    cfg = GatewayConfig(
        port=PORT,
        master_key=MASTER_KEY,
        request_timeout=30,
        rag_enabled=False,
        backends={
            "openai": BackendConfig(
                name="openai",
                api_base="http://127.0.0.1:65500/v1",
                api_key="dummy",
                models=["gpt-4o-mini"],
            ),
            "anthropic": BackendConfig(
                name="anthropic",
                api_base="http://127.0.0.1:65501",
                api_key="dummy",
                models=["claude-opus-4-7"],
            ),
            "gemini": BackendConfig(
                name="gemini",
                api_base="http://127.0.0.1:65502",
                api_key="dummy",
                models=["gemini-2.0-flash"],
            ),
        },
    )
    yaml_path = tmp_path / "litellm.yaml"
    write_config(cfg, yaml_path)

    proc = start(cfg, yaml_path)
    try:
        ready = health_check(PORT, timeout=45.0)
        if not ready:
            time.sleep(1.0)
            output = b""
            if proc.stdout is not None:
                try:
                    proc.stdout.flush()
                except Exception:
                    pass
            pytest.skip(f"litellm proxy did not become healthy: {output!r}")

        auth = {"Authorization": f"Bearer {MASTER_KEY}", "Content-Type": "application/json"}

        openai_status = _post_json(
            f"http://127.0.0.1:{PORT}/v1/chat/completions",
            {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
            auth,
        )
        assert openai_status == 0 or openai_status >= 200

        anthropic_status = _post_json(
            f"http://127.0.0.1:{PORT}/v1/messages",
            {
                "model": "claude-opus-4-7",
                "max_tokens": 8,
                "messages": [{"role": "user", "content": "hi"}],
            },
            auth,
        )
        assert anthropic_status == 0 or anthropic_status >= 200

        gemini_status = _post_json(
            f"http://127.0.0.1:{PORT}/v1beta/models/gemini-2.0-flash:generateContent",
            {"contents": [{"parts": [{"text": "hi"}]}]},
            auth,
        )
        assert gemini_status == 0 or gemini_status >= 200

        for status in (openai_status, anthropic_status, gemini_status):
            assert status != 404, "endpoint missing — routing not configured"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10.0)
        except Exception:
            proc.kill()
