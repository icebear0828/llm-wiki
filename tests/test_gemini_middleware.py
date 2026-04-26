from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from llmwiki.gateway.gemini_middleware import GeminiRAGMiddleware
from llmwiki.rag.index import Hit
from llmwiki.vault import Vault


class _FakeIndex:
    def __init__(self, hits: list[Hit] | None = None) -> None:
        self._hits = hits or [
            Hit(
                path=Path("/x/wiki/foo.md"),
                rel_path="wiki/foo.md",
                title="Foo",
                snippet="foo body content here",
                score=0.9,
            )
        ]
        self.calls: list[tuple[str, int]] = []

    def query(self, text: str, k: int = 5) -> list[Hit]:
        self.calls.append((text, k))
        return self._hits


def _vault(tmp_path: Path) -> Vault:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "raw").mkdir()
    (tmp_path / "wiki").mkdir()
    (tmp_path / "assets").mkdir()
    return Vault(root=tmp_path)


def _scope(path: str, method: str = "POST", headers: list[tuple[bytes, bytes]] | None = None) -> dict[str, Any]:
    return {
        "type": "http",
        "method": method,
        "path": path,
        "headers": headers or [(b"content-type", b"application/json")],
    }


async def _run_middleware(
    mw: GeminiRAGMiddleware, scope: dict[str, Any], body: bytes
) -> tuple[dict[str, Any], bytes]:
    """Drive the middleware once. Returns (scope_passed_through, body_passed_through)."""
    received = {"scope": None, "body": b""}

    async def inner(scope_in: dict[str, Any], receive: Any, send: Any) -> None:
        received["scope"] = scope_in
        while True:
            msg = await receive()
            if msg["type"] != "http.request":
                break
            received["body"] += msg.get("body", b"")
            if not msg.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})

    mw.app = inner

    sent_request = False

    async def receive() -> dict[str, Any]:
        nonlocal sent_request
        if sent_request:
            return {"type": "http.disconnect"}
        sent_request = True
        return {"type": "http.request", "body": body, "more_body": False}

    sends: list[dict[str, Any]] = []

    async def send(msg: dict[str, Any]) -> None:
        sends.append(msg)

    await mw(scope, receive, send)
    return received["scope"], received["body"]


@pytest.mark.asyncio
async def test_injects_systeminstruction_on_generate_content(tmp_path: Path) -> None:
    idx = _FakeIndex()
    mw = GeminiRAGMiddleware(app=lambda *a: None, vault=_vault(tmp_path), top_k=3, min_query_length=5)
    mw._index = idx  # bypass Vault.discover

    body = json.dumps(
        {
            "contents": [
                {"role": "user", "parts": [{"text": "tell me about foo bar baz topic"}]}
            ]
        }
    ).encode("utf-8")
    scope, passed_body = await _run_middleware(
        mw, _scope("/v1beta/models/gemini-2.5-flash:generateContent"), body
    )

    assert idx.calls, "RAG should have queried"
    parsed = json.loads(passed_body)
    assert "systemInstruction" in parsed
    assert "Relevant context" in parsed["systemInstruction"]["parts"][0]["text"]
    assert "Foo (file: wiki/foo.md)" in parsed["systemInstruction"]["parts"][0]["text"]
    # content-length header was rewritten
    headers = dict(scope["headers"])
    assert int(headers[b"content-length"]) == len(passed_body)


@pytest.mark.asyncio
async def test_passthrough_for_non_gemini_path(tmp_path: Path) -> None:
    idx = _FakeIndex()
    mw = GeminiRAGMiddleware(app=lambda *a: None, vault=_vault(tmp_path))
    mw._index = idx

    body = b'{"messages":[{"role":"user","content":"hi"}]}'
    _, passed = await _run_middleware(mw, _scope("/v1/chat/completions"), body)
    assert passed == body
    assert not idx.calls


@pytest.mark.asyncio
async def test_passthrough_for_get_method(tmp_path: Path) -> None:
    idx = _FakeIndex()
    mw = GeminiRAGMiddleware(app=lambda *a: None, vault=_vault(tmp_path))
    mw._index = idx

    _, passed = await _run_middleware(
        mw, _scope("/v1beta/models/gemini-2.5-flash:generateContent", method="GET"), b""
    )
    assert passed == b""
    assert not idx.calls


@pytest.mark.asyncio
async def test_passthrough_for_short_query(tmp_path: Path) -> None:
    idx = _FakeIndex()
    mw = GeminiRAGMiddleware(app=lambda *a: None, vault=_vault(tmp_path), min_query_length=20)
    mw._index = idx

    body = json.dumps(
        {"contents": [{"role": "user", "parts": [{"text": "hi"}]}]}
    ).encode("utf-8")
    _, passed = await _run_middleware(
        mw, _scope("/v1beta/models/gemini-2.5-flash:generateContent"), body
    )
    assert passed == body
    assert not idx.calls


@pytest.mark.asyncio
async def test_passthrough_for_skip_header(tmp_path: Path) -> None:
    idx = _FakeIndex()
    mw = GeminiRAGMiddleware(app=lambda *a: None, vault=_vault(tmp_path))
    mw._index = idx

    body = json.dumps(
        {"contents": [{"role": "user", "parts": [{"text": "long enough query text"}]}]}
    ).encode("utf-8")
    headers = [
        (b"content-type", b"application/json"),
        (b"x-llmwiki-skip-rag", b"1"),
    ]
    _, passed = await _run_middleware(
        mw,
        _scope("/v1beta/models/gemini-2.5-flash:generateContent", headers=headers),
        body,
    )
    assert passed == body
    assert not idx.calls


@pytest.mark.asyncio
async def test_passthrough_on_invalid_json(tmp_path: Path) -> None:
    idx = _FakeIndex()
    mw = GeminiRAGMiddleware(app=lambda *a: None, vault=_vault(tmp_path))
    mw._index = idx

    body = b"this is not json"
    _, passed = await _run_middleware(
        mw, _scope("/v1beta/models/gemini-2.5-flash:generateContent"), body
    )
    assert passed == body
    assert not idx.calls


@pytest.mark.asyncio
async def test_passthrough_when_index_raises(tmp_path: Path) -> None:
    class Boom:
        def query(self, text: str, k: int = 5) -> list[Hit]:
            raise RuntimeError("boom")

    mw = GeminiRAGMiddleware(app=lambda *a: None, vault=_vault(tmp_path), min_query_length=5)
    mw._index = Boom()

    body = json.dumps(
        {"contents": [{"role": "user", "parts": [{"text": "long enough query text"}]}]}
    ).encode("utf-8")
    _, passed = await _run_middleware(
        mw, _scope("/v1beta/models/gemini-2.5-flash:generateContent"), body
    )
    assert passed == body  # body unchanged on index error


@pytest.mark.asyncio
async def test_matches_stream_generate_content(tmp_path: Path) -> None:
    idx = _FakeIndex()
    mw = GeminiRAGMiddleware(app=lambda *a: None, vault=_vault(tmp_path), min_query_length=5)
    mw._index = idx

    body = json.dumps(
        {"contents": [{"role": "user", "parts": [{"text": "long enough query text"}]}]}
    ).encode("utf-8")
    _, passed = await _run_middleware(
        mw,
        _scope("/v1beta/models/gemini-2.5-flash:streamGenerateContent"),
        body,
    )
    parsed = json.loads(passed)
    assert "systemInstruction" in parsed
