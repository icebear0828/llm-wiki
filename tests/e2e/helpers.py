from __future__ import annotations

import json
import socket
import time
from pathlib import Path
from urllib import error, request

REPO_ROOT = Path(__file__).resolve().parents[2]


def make_vault(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text("[project]\nname='e2e-vault'\n", encoding="utf-8")
    for dirname in ("raw", "wiki", "assets"):
        (root / dirname).mkdir(exist_ok=True)
    return root


def free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_http_ok(url: str, *, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with request.urlopen(url, timeout=2.0) as resp:
                if 200 <= int(resp.status) < 500:
                    return True
        except (error.URLError, ConnectionError, TimeoutError, OSError):
            time.sleep(0.25)
    return False


def post_json(url: str, payload: dict[str, object]) -> tuple[int, str]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=10.0) as resp:
        return int(resp.status), resp.read().decode("utf-8")
