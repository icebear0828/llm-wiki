from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from urllib import error, request

from .config import GatewayConfig


def _resolve_uvicorn() -> str:
    binary = shutil.which("uvicorn")
    if binary is None:
        raise FileNotFoundError(
            "uvicorn not found on PATH. Install with `uv sync` after litellm[proxy] "
            "(uvicorn is a transitive dep)."
        )
    return binary


def start(cfg: GatewayConfig, generated_yaml: Path) -> subprocess.Popen[bytes]:
    """Launch our ASGI launcher (LiteLLM proxy app + Gemini RAG middleware)
    via uvicorn. Earlier we shelled out to the `litellm` CLI directly; that
    works but precludes adding ASGI middleware on routes whose handlers bypass
    proxy_logging_obj.pre_call_hook (notably /v1beta/.../generateContent)."""
    binary = _resolve_uvicorn()
    cmd = [
        binary,
        "llmwiki.gateway.launcher:app",
        "--port",
        str(cfg.port),
        "--host",
        "127.0.0.1",
        "--log-level",
        "info",
    ]
    env = {
        **os.environ,
        "LLMWIKI_GATEWAY_YAML": str(generated_yaml),
        "LLMWIKI_RAG_ENABLED": "1" if cfg.rag_enabled else "0",
        "LLMWIKI_RAG_TOP_K": str(cfg.rag_top_k),
        "LLMWIKI_RAG_MIN_Q": str(cfg.rag_min_query_length),
    }
    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
    )


def health_check(port: int, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    url = f"http://127.0.0.1:{port}/health/liveliness"
    fallback_url = f"http://127.0.0.1:{port}/health"
    while time.monotonic() < deadline:
        for candidate in (url, fallback_url):
            try:
                with request.urlopen(candidate, timeout=2.0) as resp:
                    if 200 <= resp.status < 500:
                        return True
            except (error.URLError, error.HTTPError, ConnectionError, TimeoutError, OSError):
                continue
        time.sleep(0.5)
    return False
