from __future__ import annotations

import json
import subprocess
from pathlib import Path
from urllib import error, request

import pytest

from tests.e2e.helpers import (
    REPO_ROOT,
    free_tcp_port,
    make_vault,
    post_json,
    wait_for_http_ok,
)

pytestmark = pytest.mark.e2e


def test_wikictl_im_http_accepts_text_ingest_over_real_localhost(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    port = free_tcp_port()
    proc = subprocess.Popen(
        [
            "uv",
            "run",
            "wikictl",
            "im",
            "http",
            "--vault",
            str(vault),
            "--port",
            str(port),
        ],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        assert wait_for_http_ok(f"http://127.0.0.1:{port}/health", timeout=30.0)
        status, body = post_json(
            f"http://127.0.0.1:{port}/ingest",
            {
                "kind": "text",
                "payload": "E2E HTTP ingest body",
                "tags": ["task/report"],
                "source": "e2e:http",
                "title": "E2E HTTP ingest",
            },
        )

        assert status == 200
        payload = json.loads(body)
        note_path = Path(payload["path"])
        assert note_path.is_file()
        assert note_path.parent == vault / "raw"
        text = note_path.read_text(encoding="utf-8")
        assert "E2E HTTP ingest body" in text
        assert "task/report" in text
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10.0)


def test_wikictl_im_http_rejects_bad_token_over_real_localhost(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    (vault / "im.toml").write_text('http_token = "secret-token"\n', encoding="utf-8")
    port = free_tcp_port()
    proc = subprocess.Popen(
        [
            "uv",
            "run",
            "wikictl",
            "im",
            "http",
            "--vault",
            str(vault),
            "--port",
            str(port),
        ],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        assert wait_for_http_ok(f"http://127.0.0.1:{port}/health", timeout=30.0)
        body = json.dumps({"kind": "text", "payload": "should not write"}).encode()
        req = request.Request(
            f"http://127.0.0.1:{port}/ingest",
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Llmwiki-Token": "wrong",
            },
            method="POST",
        )
        with pytest.raises(error.HTTPError):
            request.urlopen(req, timeout=10.0)
        assert list((vault / "raw").glob("*.md")) == []
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10.0)
