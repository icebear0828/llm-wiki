from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import yaml as pyyaml

from llmwiki.gateway.config import BackendConfig, GatewayConfig
from llmwiki.gateway.litellm_config import (
    RAG_SHIM_CALLBACK_PATH,
    RAG_SHIM_FILENAME,
    render_yaml,
    write_config,
)


def _cfg(**kwargs: object) -> GatewayConfig:
    base = GatewayConfig(
        backends={
            "openai": BackendConfig(
                name="openai",
                api_base="http://localhost:11454/v1",
                api_key="dummy",
                models=["gpt-4o"],
            ),
        },
    )
    return replace(base, **kwargs)


def test_render_yaml_includes_rag_callback_when_enabled() -> None:
    out = render_yaml(_cfg(rag_enabled=True))
    assert RAG_SHIM_CALLBACK_PATH in out


def test_render_yaml_omits_rag_callback_when_disabled() -> None:
    out = render_yaml(_cfg(rag_enabled=False))
    assert RAG_SHIM_CALLBACK_PATH not in out


def test_render_yaml_with_rag_callback_is_valid_yaml() -> None:
    parsed = pyyaml.safe_load(render_yaml(_cfg(rag_enabled=True)))
    assert isinstance(parsed, dict)
    assert parsed["litellm_settings"]["callbacks"] == RAG_SHIM_CALLBACK_PATH


def test_render_yaml_without_rag_callback_is_valid_yaml() -> None:
    parsed = pyyaml.safe_load(render_yaml(_cfg(rag_enabled=False)))
    assert isinstance(parsed, dict)
    assert "callbacks" not in parsed["litellm_settings"]


def test_write_config_drops_shim_when_rag_enabled(tmp_path: Path) -> None:
    out = tmp_path / "litellm.yaml"
    write_config(_cfg(rag_enabled=True), out)
    shim = tmp_path / RAG_SHIM_FILENAME
    assert shim.is_file()
    body = shim.read_text(encoding="utf-8")
    assert "from llmwiki.gateway.rag_callback import rag_instance" in body


def test_write_config_no_shim_when_rag_disabled(tmp_path: Path) -> None:
    out = tmp_path / "litellm.yaml"
    write_config(_cfg(rag_enabled=False), out)
    assert not (tmp_path / RAG_SHIM_FILENAME).exists()
