"""Programmatic uvicorn entry point: imports LiteLLM's proxy app and wraps it
with our RAG middleware (used for routes LiteLLM's pre_call_hook doesn't cover,
notably /v1beta/.../generateContent).

The CONFIG_FILE_PATH env var must be set before this module imports
litellm.proxy.proxy_server, otherwise LiteLLM falls back to defaults and our
model_list / master_key never load.
"""
from __future__ import annotations

import os

# Must set BEFORE importing litellm.proxy.proxy_server
_yaml = os.environ.get("LLMWIKI_GATEWAY_YAML")
if _yaml:
    os.environ["CONFIG_FILE_PATH"] = _yaml

from litellm.proxy.proxy_server import app as _litellm_app  # noqa: E402

from llmwiki.gateway.gemini_middleware import GeminiRAGMiddleware  # noqa: E402

_top_k = int(os.environ.get("LLMWIKI_RAG_TOP_K", "5"))
_min_q = int(os.environ.get("LLMWIKI_RAG_MIN_Q", "10"))
_rag_enabled = os.environ.get("LLMWIKI_RAG_ENABLED", "1") not in ("0", "false", "")

if _rag_enabled:
    _litellm_app.add_middleware(
        GeminiRAGMiddleware,
        top_k=_top_k,
        min_query_length=_min_q,
    )

app = _litellm_app
