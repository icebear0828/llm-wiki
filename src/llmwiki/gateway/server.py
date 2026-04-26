from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path
from urllib import error, request

from .config import GatewayConfig


def _resolve_litellm() -> str:
    binary = shutil.which("litellm")
    if binary is None:
        raise FileNotFoundError(
            "litellm executable not found on PATH. Install with `uv sync` "
            "after adding litellm[proxy] to dependencies."
        )
    return binary


def start(cfg: GatewayConfig, generated_yaml: Path) -> subprocess.Popen[bytes]:
    binary = _resolve_litellm()
    cmd = [
        binary,
        "--config",
        str(generated_yaml),
        "--port",
        str(cfg.port),
        "--host",
        "127.0.0.1",
    ]
    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
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
