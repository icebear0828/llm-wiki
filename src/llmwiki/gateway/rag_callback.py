from __future__ import annotations

from typing import Literal, Protocol

from litellm.integrations.custom_logger import CustomLogger

from llmwiki.rag.index import Hit, get_index
from llmwiki.vault import Vault

CallType = Literal[
    "completion",
    "acompletion",
    "text_completion",
    "atext_completion",
    "embeddings",
    "image_generation",
    "moderation",
    "audio_transcription",
    "pass_through_endpoint",
    "rerank",
]

_COMPLETION_CALL_TYPES = frozenset((
    "completion",
    "acompletion",
    "text_completion",
    "atext_completion",
    "anthropic_messages",       # /v1/messages route
    "agenerate_content",        # /v1beta/.../generateContent route
    "generate_content",
    "astream_generate_content",
    "stream_generate_content",
))

SKIP_HEADER = "x-llmwiki-skip-rag"


class _IndexProto(Protocol):
    def query(self, text: str, k: int = 5) -> list[Hit]: ...


def _extract_text_parts(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for part in content:
            if isinstance(part, dict):
                t = part.get("text")
                if isinstance(t, str):
                    chunks.append(t)
        return "\n".join(chunks)
    return ""


def _extract_query_from_messages(messages: object) -> str:
    if not isinstance(messages, list):
        return ""
    for msg in reversed(messages):
        if not isinstance(msg, dict):
            continue
        if msg.get("role") != "user":
            continue
        return _extract_text_parts(msg.get("content"))
    return ""


def _extract_query_from_contents(contents: object) -> str:
    if not isinstance(contents, list):
        return ""
    for entry in reversed(contents):
        if not isinstance(entry, dict):
            continue
        role = entry.get("role")
        if role is not None and role != "user":
            continue
        parts = entry.get("parts")
        if not isinstance(parts, list):
            continue
        chunks: list[str] = []
        for part in parts:
            if isinstance(part, dict):
                t = part.get("text")
                if isinstance(t, str):
                    chunks.append(t)
        joined = "\n".join(chunks)
        if joined:
            return joined
    return ""


def _detect_format(data: dict[str, object]) -> str:
    if "contents" in data and "messages" not in data:
        return "gemini"
    if "system" in data and "messages" in data:
        return "anthropic"
    if "messages" in data:
        return "openai"
    return "unknown"


def _has_tools(data: dict[str, object]) -> bool:
    if data.get("tools"):
        return True
    if data.get("functions"):
        return True
    if data.get("function_call"):
        return True
    if data.get("tool_choice") not in (None, "none", "auto"):
        return True
    return False


def _should_skip_via_metadata(
    user_api_key_dict: object, data: dict[str, object]
) -> bool:
    candidates: list[object] = []
    meta_attr = getattr(user_api_key_dict, "metadata", None)
    if meta_attr is not None:
        candidates.append(meta_attr)
    candidates.append(data.get("metadata"))
    candidates.append(data.get("headers"))
    candidates.append(data.get("proxy_server_request"))
    for cand in candidates:
        if isinstance(cand, dict):
            for key, value in cand.items():
                if isinstance(key, str) and key.lower() == SKIP_HEADER:
                    if value:
                        return True
            headers = cand.get("headers")
            if isinstance(headers, dict):
                for key, value in headers.items():
                    if isinstance(key, str) and key.lower() == SKIP_HEADER:
                        if value:
                            return True
    return False


def _build_context(hits: list[Hit]) -> str:
    parts: list[str] = ["Relevant context from your private knowledge base (wiki):", ""]
    for i, hit in enumerate(hits, start=1):
        parts.append(f"[{i}] {hit.title} (file: {hit.rel_path})")
        parts.append(hit.snippet)
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def _inject_openai(data: dict[str, object], ctx: str) -> None:
    messages = data.get("messages")
    if not isinstance(messages, list):
        return
    if messages and isinstance(messages[0], dict) and messages[0].get("role") == "system":
        existing = messages[0].get("content")
        if isinstance(existing, str):
            messages[0]["content"] = ctx + "\n\n" + existing
        elif isinstance(existing, list):
            new_list: list[object] = [{"type": "text", "text": ctx}]
            new_list.extend(existing)
            messages[0]["content"] = new_list
        else:
            messages[0]["content"] = ctx
        return
    new_messages: list[object] = [{"role": "system", "content": ctx}]
    new_messages.extend(messages)
    data["messages"] = new_messages


def _inject_anthropic(data: dict[str, object], ctx: str) -> None:
    existing = data.get("system")
    if existing is None:
        data["system"] = ctx
        return
    if isinstance(existing, str):
        data["system"] = ctx + "\n\n" + existing
        return
    if isinstance(existing, list):
        new_list: list[object] = [{"type": "text", "text": ctx}]
        new_list.extend(existing)
        data["system"] = new_list
        return
    data["system"] = ctx


def _inject_gemini(data: dict[str, object], ctx: str) -> None:
    existing = data.get("systemInstruction")
    if existing is None:
        data["systemInstruction"] = {"parts": [{"text": ctx}]}
        return
    if isinstance(existing, dict):
        parts = existing.get("parts")
        if isinstance(parts, list):
            new_parts: list[object] = [{"text": ctx}]
            new_parts.extend(parts)
            existing["parts"] = new_parts
        else:
            existing["parts"] = [{"text": ctx}]
        return
    if isinstance(existing, str):
        data["systemInstruction"] = {"parts": [{"text": ctx + "\n\n" + existing}]}
        return
    data["systemInstruction"] = {"parts": [{"text": ctx}]}


class RAGCallback(CustomLogger):
    def __init__(
        self,
        vault: Vault,
        *,
        top_k: int = 5,
        min_query_length: int = 10,
        index: _IndexProto | None = None,
    ) -> None:
        super().__init__()
        self.vault = vault
        self.top_k = top_k
        self.min_query_length = min_query_length
        self._index: _IndexProto = index if index is not None else get_index(vault)

    def _extract_query(self, data: dict[str, object], fmt: str) -> str:
        if fmt == "gemini":
            return _extract_query_from_contents(data.get("contents"))
        if fmt in ("openai", "anthropic"):
            return _extract_query_from_messages(data.get("messages"))
        return ""

    def _inject(self, data: dict[str, object], fmt: str, ctx: str) -> None:
        if fmt == "openai":
            _inject_openai(data, ctx)
        elif fmt == "anthropic":
            _inject_anthropic(data, ctx)
        elif fmt == "gemini":
            _inject_gemini(data, ctx)

    async def async_pre_call_hook(
        self,
        user_api_key_dict: object,
        cache: object,
        data: dict[str, object],
        call_type: CallType,
    ) -> dict[str, object] | None:
        if call_type not in _COMPLETION_CALL_TYPES:
            return data
        if _should_skip_via_metadata(user_api_key_dict, data):
            return data
        if _has_tools(data):
            return data

        fmt = _detect_format(data)
        if fmt == "unknown":
            return data

        query = self._extract_query(data, fmt).strip()
        if len(query) < self.min_query_length:
            return data

        try:
            hits = self._index.query(query, k=self.top_k)
        except Exception:
            return data
        if not hits:
            return data

        ctx = _build_context(hits)
        self._inject(data, fmt, ctx)
        return data


# Lazy module-level instance. Assumes proxy is started from vault root
# (Vault.discover walks parents looking for raw/ + wiki/ + pyproject.toml).
_instance: RAGCallback | None = None


def _build_default_instance() -> RAGCallback:
    return RAGCallback(Vault.discover())


def __getattr__(name: str) -> object:
    global _instance
    if name == "rag_instance":
        if _instance is None:
            _instance = _build_default_instance()
        return _instance
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def reset_instance_for_tests() -> None:
    global _instance
    _instance = None
