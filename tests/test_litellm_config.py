from __future__ import annotations

from pathlib import Path

from llmwiki.gateway.config import BackendConfig, GatewayConfig
from llmwiki.gateway.litellm_config import render_yaml, write_config


def _sample_cfg() -> GatewayConfig:
    return GatewayConfig(
        port=8080,
        master_key="<REDACTED-MASTER-KEY>",
        request_timeout=600,
        backends={
            "openai": BackendConfig(
                name="openai",
                api_base="http://localhost:11454/v1",
                api_key="dummy",
                models=["gpt-4o", "gpt-4o-mini"],
            ),
            "anthropic": BackendConfig(
                name="anthropic",
                api_base="http://localhost:11455",
                api_key="dummy",
                models=["claude-opus-4-7"],
            ),
            "gemini": BackendConfig(
                name="gemini",
                api_base="http://localhost:11456/v1beta",
                api_key="dummy",
                models=["gemini-2.0-flash"],
            ),
        },
    )


def test_render_yaml_contains_all_three_backends() -> None:
    yaml = render_yaml(_sample_cfg())
    assert "openai/gpt-4o" in yaml
    assert "openai/gpt-4o-mini" in yaml
    assert "anthropic/claude-opus-4-7" in yaml
    assert "gemini/gemini-2.0-flash" in yaml
    assert "http://localhost:11454/v1" in yaml
    assert "http://localhost:11455" in yaml
    assert "http://localhost:11456/v1beta" in yaml


def test_render_yaml_wires_master_key_and_timeout() -> None:
    yaml = render_yaml(_sample_cfg())
    assert "master_key:" in yaml
    assert "<REDACTED-MASTER-KEY>" in yaml
    assert "request_timeout: 600" in yaml


def test_render_yaml_marks_rag_placeholder() -> None:
    yaml = render_yaml(_sample_cfg())
    assert "RAG callback added by issue #14" in yaml


def test_render_yaml_model_list_has_one_entry_per_model() -> None:
    yaml = render_yaml(_sample_cfg())
    count = yaml.count("- model_name:")
    assert count == 4  # 2 + 1 + 1


def test_render_yaml_empty_backends_uses_empty_list() -> None:
    yaml = render_yaml(GatewayConfig())
    assert "model_list:" in yaml
    assert "- model_name:" not in yaml


def test_render_yaml_is_parseable_by_pyyaml() -> None:
    import yaml as pyyaml

    parsed = pyyaml.safe_load(render_yaml(_sample_cfg()))
    assert isinstance(parsed, dict)
    assert isinstance(parsed["model_list"], list)
    assert len(parsed["model_list"]) == 4
    assert parsed["general_settings"]["master_key"] == "<REDACTED-MASTER-KEY>"
    assert parsed["litellm_settings"]["request_timeout"] == 600
    first = parsed["model_list"][0]
    assert "model_name" in first
    assert "litellm_params" in first


def test_write_config_returns_path(tmp_path: Path) -> None:
    out = tmp_path / "litellm.yaml"
    result = write_config(_sample_cfg(), out)
    assert result == out
    assert out.is_file()
    assert "model_list:" in out.read_text(encoding="utf-8")
