from __future__ import annotations

from pathlib import Path

from llmwiki.gateway.config import (
    CONFIG_FILENAME,
    BackendConfig,
    GatewayConfig,
    write_default_template,
)


def test_load_returns_defaults_when_missing(tmp_path: Path) -> None:
    cfg = GatewayConfig.load(tmp_path)
    assert cfg.port == 8080
    assert cfg.master_key == "sk-llmwiki-local"
    assert cfg.request_timeout == 600
    assert cfg.backends == {}


def test_load_parses_three_backends(tmp_path: Path) -> None:
    (tmp_path / CONFIG_FILENAME).write_text(
        """
port = 9090
master_key = "sk-test"
request_timeout = 30

[backends.openai]
api_base = "http://localhost:11454/v1"
api_key = "k1"
models = ["gpt-4o"]

[backends.anthropic]
api_base = "http://localhost:11455"
api_key = "k2"
models = ["claude-opus-4-7"]

[backends.gemini]
api_base = "http://localhost:11456/v1beta"
api_key = "k3"
models = ["gemini-2.0-flash"]
""",
        encoding="utf-8",
    )
    cfg = GatewayConfig.load(tmp_path)
    assert cfg.port == 9090
    assert cfg.master_key == "sk-test"
    assert cfg.request_timeout == 30
    assert set(cfg.backends.keys()) == {"openai", "anthropic", "gemini"}
    openai = cfg.backends["openai"]
    assert isinstance(openai, BackendConfig)
    assert openai.api_base == "http://localhost:11454/v1"
    assert openai.api_key == "k1"
    assert openai.models == ["gpt-4o"]


def test_configured_backends_filters_empty_api_base(tmp_path: Path) -> None:
    (tmp_path / CONFIG_FILENAME).write_text(
        """
[backends.openai]
api_base = "http://localhost:1/v1"
api_key = "x"
models = ["gpt-4o"]

[backends.anthropic]
api_base = ""
api_key = "x"
models = ["claude-opus-4-7"]
""",
        encoding="utf-8",
    )
    cfg = GatewayConfig.load(tmp_path)
    configured = cfg.configured_backends()
    assert set(configured.keys()) == {"openai"}


def test_write_default_template_is_idempotent(tmp_path: Path) -> None:
    path1, written1 = write_default_template(tmp_path)
    assert written1 is True
    assert path1.is_file()
    contents = path1.read_text(encoding="utf-8")
    assert "[backends.openai]" in contents
    assert "[backends.anthropic]" in contents
    assert "[backends.gemini]" in contents

    path2, written2 = write_default_template(tmp_path)
    assert written2 is False
    assert path2.read_text(encoding="utf-8") == contents


def test_default_template_mentions_rag_fields(tmp_path: Path) -> None:
    path, _ = write_default_template(tmp_path)
    contents = path.read_text(encoding="utf-8")
    assert "rag_enabled" in contents
    assert "rag_top_k" in contents
    assert "rag_min_query_length" in contents


def test_defaults_have_rag_enabled_true() -> None:
    cfg = GatewayConfig()
    assert cfg.rag_enabled is True
    assert cfg.rag_top_k == 5
    assert cfg.rag_min_query_length == 10


def test_load_rag_disabled_flag(tmp_path: Path) -> None:
    (tmp_path / CONFIG_FILENAME).write_text(
        """
rag_enabled = false
rag_top_k = 7
rag_min_query_length = 25
""",
        encoding="utf-8",
    )
    cfg = GatewayConfig.load(tmp_path)
    assert cfg.rag_enabled is False
    assert cfg.rag_top_k == 7
    assert cfg.rag_min_query_length == 25


def test_load_defaults_preserve_rag_enabled(tmp_path: Path) -> None:
    (tmp_path / CONFIG_FILENAME).write_text("port = 8080\n", encoding="utf-8")
    cfg = GatewayConfig.load(tmp_path)
    assert cfg.rag_enabled is True
    assert cfg.rag_top_k == 5
    assert cfg.rag_min_query_length == 10
