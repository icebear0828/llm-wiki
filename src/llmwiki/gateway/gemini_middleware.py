from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from typing import Any

from llmwiki.gateway.rag_callback import (
    SKIP_HEADER,
    _build_context,
    _extract_query_from_contents,
    _inject_gemini,
)
from llmwiki.rag.index import get_index
from llmwiki.vault import Vault

# /v1beta/models/<model>:generateContent  and  :streamGenerateContent
_GEMINI_PATH = re.compile(r"^/v1beta/models/[^/]+:(generate|streamGenerate)Content/?$")

ASGIScope = dict[str, Any]
ASGIMessage = dict[str, Any]
ASGIReceive = Callable[[], Awaitable[ASGIMessage]]
ASGISend = Callable[[ASGIMessage], Awaitable[None]]
ASGIApp = Callable[[ASGIScope, ASGIReceive, ASGISend], Awaitable[None]]


class GeminiRAGMiddleware:
    """ASGI middleware that injects RAG context into Gemini /v1beta/.../generateContent
    requests before LiteLLM's google_endpoints handler sees them.

    LiteLLM's `agenerate_content` route bypasses proxy_logging_obj.pre_call_hook
    entirely, so the standard CustomLogger hook (used for OpenAI + Anthropic) does
    not fire on this path. This middleware fills the gap by intercepting the body
    at the ASGI layer.

    The index is loaded lazily on the first matching request — at app-construction
    time we have no vault root yet (proxy may be started from any cwd that resolves
    via Vault.discover).
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        vault: Vault | None = None,
        top_k: int = 5,
        min_query_length: int = 10,
    ) -> None:
        self.app = app
        self._vault = vault
        self._top_k = top_k
        self._min_query_length = min_query_length
        self._index: Any = None

    def _get_index(self) -> Any:
        if self._index is not None:
            return self._index
        vault = self._vault if self._vault is not None else Vault.discover()
        self._index = get_index(vault)
        return self._index

    def _has_skip_header(self, scope: ASGIScope) -> bool:
        for k, v in scope.get("headers", []):
            if k.decode("latin-1").lower() == SKIP_HEADER and v:
                return True
        return False

    def _matches(self, scope: ASGIScope) -> bool:
        if scope.get("type") != "http":
            return False
        if scope.get("method") != "POST":
            return False
        path = scope.get("path", "")
        return bool(_GEMINI_PATH.match(path))

    async def __call__(
        self, scope: ASGIScope, receive: ASGIReceive, send: ASGISend
    ) -> None:
        if not self._matches(scope) or self._has_skip_header(scope):
            await self.app(scope, receive, send)
            return

        body = await _read_body(receive)
        new_body = self._inject_rag(body)

        if new_body == body:
            scope_to_pass = scope
        else:
            scope_to_pass = _replace_content_length(scope, len(new_body))

        await self.app(scope_to_pass, _replay_receive(new_body), send)

    def _inject_rag(self, body: bytes) -> bytes:
        if not body:
            return body
        try:
            data = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            return body
        if not isinstance(data, dict):
            return body

        query = _extract_query_from_contents(data.get("contents")).strip()
        if len(query) < self._min_query_length:
            return body
        try:
            hits = self._get_index().query(query, k=self._top_k)
        except Exception:
            return body
        if not hits:
            return body

        ctx = _build_context(hits)
        _inject_gemini(data, ctx)
        return json.dumps(data, ensure_ascii=False).encode("utf-8")


async def _read_body(receive: ASGIReceive) -> bytes:
    chunks: list[bytes] = []
    while True:
        message = await receive()
        if message["type"] != "http.request":
            continue
        chunks.append(message.get("body", b""))
        if not message.get("more_body"):
            break
    return b"".join(chunks)


def _replay_receive(body: bytes) -> ASGIReceive:
    sent = False

    async def receive() -> ASGIMessage:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return receive


def _replace_content_length(scope: ASGIScope, new_length: int) -> ASGIScope:
    new_headers: list[tuple[bytes, bytes]] = []
    for k, v in scope.get("headers", []):
        if k.decode("latin-1").lower() == "content-length":
            continue
        new_headers.append((k, v))
    new_headers.append((b"content-length", str(new_length).encode("latin-1")))
    return {**scope, "headers": new_headers}
