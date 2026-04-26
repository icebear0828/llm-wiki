from __future__ import annotations

import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from llmwiki.im import common
from llmwiki.im.config import ImConfig
from llmwiki.im.http_endpoint import create_app
from llmwiki.vault import Vault


@pytest.fixture()
def vault(tmp_path: Path) -> Vault:
    root = tmp_path / "vault"
    (root / "raw").mkdir(parents=True)
    (root / "wiki").mkdir(parents=True)
    return Vault(root=root)


@pytest.fixture()
def cfg_open() -> ImConfig:
    return ImConfig()


@pytest.fixture()
def cfg_secured() -> ImConfig:
    return ImConfig(http_token="hunter2")


def test_health(vault: Vault, cfg_open: ImConfig) -> None:
    client = TestClient(create_app(vault, cfg_open))
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_ingest_text(vault: Vault, cfg_open: ImConfig) -> None:
    client = TestClient(create_app(vault, cfg_open))
    r = client.post("/ingest", json={"kind": "text", "payload": "hello world"})
    assert r.status_code == 200
    body = r.json()
    p = Path(body["path"])
    assert p.is_file()
    assert p.parent == vault.raw


def test_ingest_url(monkeypatch: pytest.MonkeyPatch, vault: Vault, cfg_open: ImConfig) -> None:
    monkeypatch.setattr(common, "_fetch_url_markdown", lambda url, timeout: ("# Title\n\nbody", None))
    client = TestClient(create_app(vault, cfg_open))
    r = client.post("/ingest", json={"kind": "url", "payload": "https://example.com/x"})
    assert r.status_code == 200
    p = Path(r.json()["path"])
    text = p.read_text(encoding="utf-8")
    assert "# Title" in text
    assert "https://example.com/x" in text


def test_ingest_file_b64(vault: Vault, cfg_open: ImConfig) -> None:
    client = TestClient(create_app(vault, cfg_open))
    payload = base64.b64encode(b"hello world").decode("ascii")
    r = client.post(
        "/ingest",
        json={"kind": "file_b64", "payload": payload, "filename": "hello.txt"},
    )
    assert r.status_code == 200
    p = Path(r.json()["path"])
    assert p.is_file()
    raw_files = list(vault.raw.glob("*hello.txt"))
    assert raw_files, "copied file should appear in raw/"
    assert raw_files[0].read_bytes() == b"hello world"


def test_ingest_file_multipart(vault: Vault, cfg_open: ImConfig) -> None:
    client = TestClient(create_app(vault, cfg_open))
    r = client.post(
        "/ingest/file",
        files={"file": ("hello.txt", b"hello upload", "text/plain")},
        data={"tags": "task/audio,task/extra", "title": "Custom"},
    )
    assert r.status_code == 200
    p = Path(r.json()["path"])
    assert p.is_file()
    text = p.read_text(encoding="utf-8")
    assert "Custom" in text
    assert "task/audio" in text


def test_auth_bad_token(vault: Vault, cfg_secured: ImConfig) -> None:
    client = TestClient(create_app(vault, cfg_secured))
    r = client.post(
        "/ingest",
        json={"kind": "text", "payload": "hi"},
        headers={"X-Llmwiki-Token": "wrong"},
    )
    assert r.status_code == 401
    assert "error" in r.json()


def test_auth_missing_token(vault: Vault, cfg_secured: ImConfig) -> None:
    client = TestClient(create_app(vault, cfg_secured))
    r = client.post("/ingest", json={"kind": "text", "payload": "hi"})
    assert r.status_code == 401


def test_auth_correct_token(vault: Vault, cfg_secured: ImConfig) -> None:
    client = TestClient(create_app(vault, cfg_secured))
    r = client.post(
        "/ingest",
        json={"kind": "text", "payload": "hi"},
        headers={"X-Llmwiki-Token": "hunter2"},
    )
    assert r.status_code == 200


def test_no_auth_when_token_none(vault: Vault, cfg_open: ImConfig) -> None:
    client = TestClient(create_app(vault, cfg_open))
    r = client.post("/ingest", json={"kind": "text", "payload": "hi"})
    assert r.status_code == 200


def test_400_missing_payload(vault: Vault, cfg_open: ImConfig) -> None:
    client = TestClient(create_app(vault, cfg_open))
    r = client.post("/ingest", json={"kind": "text", "payload": ""})
    assert r.status_code == 400
    assert "error" in r.json()


def test_400_file_b64_missing_filename(vault: Vault, cfg_open: ImConfig) -> None:
    client = TestClient(create_app(vault, cfg_open))
    payload = base64.b64encode(b"x").decode("ascii")
    r = client.post("/ingest", json={"kind": "file_b64", "payload": payload})
    assert r.status_code == 400


def test_400_file_b64_bad_base64(vault: Vault, cfg_open: ImConfig) -> None:
    client = TestClient(create_app(vault, cfg_open))
    r = client.post(
        "/ingest",
        json={"kind": "file_b64", "payload": "not base64!!!", "filename": "x.txt"},
    )
    assert r.status_code == 400
