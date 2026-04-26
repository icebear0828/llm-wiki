from __future__ import annotations

from pathlib import Path

import pytest

from llmwiki.gateway.rag_callback import RAGCallback, _build_context
from llmwiki.rag.index import Hit
from llmwiki.vault import Vault


class FakeIndex:
    def __init__(self, hits: list[Hit]) -> None:
        self.hits = hits
        self.calls: list[tuple[str, int]] = []

    def query(self, text: str, k: int = 5) -> list[Hit]:
        self.calls.append((text, k))
        return list(self.hits)


def _vault(tmp_path: Path) -> Vault:
    (tmp_path / "raw").mkdir()
    (tmp_path / "wiki").mkdir()
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    return Vault(tmp_path)


def _hits() -> list[Hit]:
    return [
        Hit(
            path=Path("/x/wiki/foo.md"),
            rel_path="wiki/foo.md",
            title="Foo",
            snippet="foo body",
            score=0.9,
        ),
        Hit(
            path=Path("/x/wiki/bar.md"),
            rel_path="wiki/bar.md",
            title="Bar",
            snippet="bar body",
            score=0.8,
        ),
    ]


def _make(tmp_path: Path, hits: list[Hit] | None = None) -> tuple[RAGCallback, FakeIndex]:
    idx = FakeIndex(hits if hits is not None else _hits())
    cb = RAGCallback(_vault(tmp_path), top_k=3, min_query_length=10, index=idx)
    return cb, idx


@pytest.mark.asyncio
async def test_openai_format_injects_system_message(tmp_path: Path) -> None:
    cb, idx = _make(tmp_path)
    data: dict[str, object] = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "tell me about widgets please"}],
    }
    out = await cb.async_pre_call_hook({}, None, data, "completion")
    assert out is data
    msgs = data["messages"]
    assert isinstance(msgs, list)
    assert msgs[0]["role"] == "system"
    assert "Relevant context from your private knowledge base" in msgs[0]["content"]
    assert "Foo" in msgs[0]["content"]
    assert "wiki/foo.md" in msgs[0]["content"]
    assert idx.calls and idx.calls[0][1] == 3


@pytest.mark.asyncio
async def test_openai_merges_existing_system_string(tmp_path: Path) -> None:
    cb, _ = _make(tmp_path)
    data: dict[str, object] = {
        "messages": [
            {"role": "system", "content": "you are helpful"},
            {"role": "user", "content": "what is the answer to my real question"},
        ],
    }
    await cb.async_pre_call_hook({}, None, data, "completion")
    msgs = data["messages"]
    assert isinstance(msgs, list)
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[0]["content"].endswith("you are helpful")
    assert "Relevant context" in msgs[0]["content"]


@pytest.mark.asyncio
async def test_openai_merges_existing_system_list(tmp_path: Path) -> None:
    cb, _ = _make(tmp_path)
    data: dict[str, object] = {
        "messages": [
            {"role": "system", "content": [{"type": "text", "text": "be terse"}]},
            {"role": "user", "content": "what about widgets in detail"},
        ],
    }
    await cb.async_pre_call_hook({}, None, data, "completion")
    msgs = data["messages"]
    assert isinstance(msgs, list)
    assert len(msgs) == 2
    sys_content = msgs[0]["content"]
    assert isinstance(sys_content, list)
    assert sys_content[0]["text"].startswith("Relevant context")
    assert sys_content[-1]["text"] == "be terse"


@pytest.mark.asyncio
async def test_openai_user_content_as_list_concats_text(tmp_path: Path) -> None:
    cb, idx = _make(tmp_path)
    data: dict[str, object] = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "explain widgets"},
                    {"type": "text", "text": "in detail please"},
                ],
            }
        ],
    }
    await cb.async_pre_call_hook({}, None, data, "completion")
    assert idx.calls
    assert "explain widgets" in idx.calls[0][0]
    assert "in detail please" in idx.calls[0][0]


@pytest.mark.asyncio
async def test_anthropic_no_system_sets_string(tmp_path: Path) -> None:
    cb, _ = _make(tmp_path)
    data: dict[str, object] = {
        "model": "claude",
        "system": None,
        "messages": [{"role": "user", "content": "discuss the long topic now"}],
    }
    out = await cb.async_pre_call_hook({}, None, data, "completion")
    assert out is data
    sys = data["system"]
    assert isinstance(sys, str)
    assert "Relevant context" in sys


@pytest.mark.asyncio
async def test_anthropic_existing_system_string_prepends(tmp_path: Path) -> None:
    cb, _ = _make(tmp_path)
    data: dict[str, object] = {
        "system": "be polite",
        "messages": [{"role": "user", "content": "discuss the long topic now"}],
    }
    await cb.async_pre_call_hook({}, None, data, "completion")
    sys = data["system"]
    assert isinstance(sys, str)
    assert "be polite" in sys
    assert sys.startswith("Relevant context")


@pytest.mark.asyncio
async def test_anthropic_existing_system_list_prepends(tmp_path: Path) -> None:
    cb, _ = _make(tmp_path)
    data: dict[str, object] = {
        "system": [{"type": "text", "text": "be polite"}],
        "messages": [{"role": "user", "content": "discuss the long topic now"}],
    }
    await cb.async_pre_call_hook({}, None, data, "completion")
    sys = data["system"]
    assert isinstance(sys, list)
    assert sys[0]["text"].startswith("Relevant context")
    assert sys[-1]["text"] == "be polite"


@pytest.mark.asyncio
async def test_gemini_format_sets_system_instruction(tmp_path: Path) -> None:
    cb, idx = _make(tmp_path)
    data: dict[str, object] = {
        "contents": [
            {"role": "user", "parts": [{"text": "what about the widgets again"}]},
        ],
    }
    out = await cb.async_pre_call_hook({}, None, data, "completion")
    assert out is data
    si = data["systemInstruction"]
    assert isinstance(si, dict)
    parts = si["parts"]
    assert isinstance(parts, list)
    assert "Relevant context" in parts[0]["text"]
    assert idx.calls
    assert "widgets" in idx.calls[0][0]


@pytest.mark.asyncio
async def test_gemini_existing_system_instruction_prepends(tmp_path: Path) -> None:
    cb, _ = _make(tmp_path)
    data: dict[str, object] = {
        "contents": [
            {"role": "user", "parts": [{"text": "what about the widgets again"}]},
        ],
        "systemInstruction": {"parts": [{"text": "be brief"}]},
    }
    await cb.async_pre_call_hook({}, None, data, "completion")
    si = data["systemInstruction"]
    assert isinstance(si, dict)
    parts = si["parts"]
    assert isinstance(parts, list)
    assert parts[0]["text"].startswith("Relevant context")
    assert parts[-1]["text"] == "be brief"


@pytest.mark.asyncio
async def test_short_query_skips_injection(tmp_path: Path) -> None:
    cb, idx = _make(tmp_path)
    data: dict[str, object] = {
        "messages": [{"role": "user", "content": "hi"}],
    }
    snapshot = {"messages": list(data["messages"])}
    await cb.async_pre_call_hook({}, None, data, "completion")
    assert data["messages"] == snapshot["messages"]
    assert not idx.calls


@pytest.mark.asyncio
async def test_tool_call_request_skipped(tmp_path: Path) -> None:
    cb, idx = _make(tmp_path)
    data: dict[str, object] = {
        "messages": [{"role": "user", "content": "use a tool to compute primes"}],
        "tools": [{"type": "function", "function": {"name": "x"}}],
    }
    await cb.async_pre_call_hook({}, None, data, "completion")
    assert data["messages"][0]["role"] == "user"
    assert not idx.calls


@pytest.mark.asyncio
async def test_skip_header_in_metadata(tmp_path: Path) -> None:
    cb, idx = _make(tmp_path)
    data: dict[str, object] = {
        "messages": [{"role": "user", "content": "discuss the long topic now"}],
        "metadata": {"headers": {"X-LLMWiki-Skip-RAG": "1"}},
    }
    await cb.async_pre_call_hook({}, None, data, "completion")
    assert not idx.calls


@pytest.mark.asyncio
async def test_skip_header_on_user_api_key_metadata(tmp_path: Path) -> None:
    cb, idx = _make(tmp_path)

    class FakeKey:
        metadata = {"x-llmwiki-skip-rag": "true"}

    data: dict[str, object] = {
        "messages": [{"role": "user", "content": "discuss the long topic now"}],
    }
    await cb.async_pre_call_hook(FakeKey(), None, data, "completion")
    assert not idx.calls


@pytest.mark.asyncio
async def test_empty_hits_no_injection(tmp_path: Path) -> None:
    cb, _ = _make(tmp_path, hits=[])
    data: dict[str, object] = {
        "messages": [{"role": "user", "content": "discuss the long topic now"}],
    }
    out = await cb.async_pre_call_hook({}, None, data, "completion")
    assert out is data
    assert len(data["messages"]) == 1
    assert data["messages"][0]["role"] == "user"


@pytest.mark.asyncio
async def test_index_exception_does_not_crash(tmp_path: Path) -> None:
    class Boom:
        def query(self, text: str, k: int = 5) -> list[Hit]:
            raise RuntimeError("boom")

    cb = RAGCallback(_vault(tmp_path), top_k=3, min_query_length=10, index=Boom())
    data: dict[str, object] = {
        "messages": [{"role": "user", "content": "discuss the long topic now"}],
    }
    out = await cb.async_pre_call_hook({}, None, data, "completion")
    assert out is data
    assert len(data["messages"]) == 1


@pytest.mark.asyncio
async def test_non_completion_call_type_passthrough(tmp_path: Path) -> None:
    cb, idx = _make(tmp_path)
    data: dict[str, object] = {
        "messages": [{"role": "user", "content": "discuss the long topic now"}],
    }
    await cb.async_pre_call_hook({}, None, data, "embeddings")
    assert not idx.calls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "call_type",
    ["acompletion", "anthropic_messages", "agenerate_content", "atext_completion"],
)
async def test_router_call_types_trigger_rag(tmp_path: Path, call_type: str) -> None:
    # Regression: LiteLLM passes call_type="acompletion" / "anthropic_messages" /
    # "agenerate_content" depending on the incoming route. Earlier we only matched
    # "completion" and silently skipped injection for /v1/chat/completions and
    # /v1/messages.
    cb, idx = _make(tmp_path)
    data: dict[str, object] = {
        "messages": [{"role": "user", "content": "discuss the long topic now"}],
    }
    await cb.async_pre_call_hook({}, None, data, call_type)
    assert idx.calls, f"RAG should fire for call_type={call_type}"


def test_build_context_template_format() -> None:
    ctx = _build_context(_hits())
    assert ctx.startswith("Relevant context from your private knowledge base (wiki):")
    assert "[1] Foo (file: wiki/foo.md)" in ctx
    assert "[2] Bar (file: wiki/bar.md)" in ctx
    assert "foo body" in ctx
    assert "bar body" in ctx


@pytest.mark.asyncio
async def test_walks_messages_to_find_last_user(tmp_path: Path) -> None:
    cb, idx = _make(tmp_path)
    data: dict[str, object] = {
        "messages": [
            {"role": "user", "content": "first user query that is long enough"},
            {"role": "assistant", "content": "some assistant reply here"},
            {"role": "user", "content": "second and latest user question"},
        ],
    }
    await cb.async_pre_call_hook({}, None, data, "completion")
    assert idx.calls
    assert "second and latest user question" in idx.calls[0][0]
