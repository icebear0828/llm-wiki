from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_FILENAME = "gateway.toml"

DEFAULT_MODELS: dict[str, list[str]] = {
    "openai": ["gpt-4o", "gpt-4o-mini"],
    "anthropic": ["claude-sonnet-4-6", "claude-opus-4-7"],
    "gemini": ["gemini-2.0-flash"],
}

DEFAULT_TEMPLATE = """\
port = 8080
master_key = "sk-llmwiki-local"
request_timeout = 600

# RAG injection (issue #14)
# rag_enabled = true
# rag_top_k = 5
# rag_min_query_length = 10

[backends.openai]
api_base = ""
api_key = "dummy"
models = ["gpt-4o", "gpt-4o-mini"]

[backends.anthropic]
api_base = ""
api_key = "dummy"
models = ["claude-sonnet-4-6", "claude-opus-4-7"]

[backends.gemini]
api_base = ""
api_key = "dummy"
models = ["gemini-2.0-flash"]
"""


@dataclass(frozen=True)
class BackendConfig:
    name: str
    api_base: str
    api_key: str = ""
    models: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class GatewayConfig:
    port: int = 8080
    master_key: str = "sk-llmwiki-local"
    request_timeout: int = 600
    backends: dict[str, BackendConfig] = field(default_factory=dict)
    rag_enabled: bool = True
    rag_top_k: int = 5
    rag_min_query_length: int = 10

    @classmethod
    def load(cls, vault_root: Path) -> "GatewayConfig":
        toml_path = Path(vault_root) / CONFIG_FILENAME
        if not toml_path.is_file():
            return cls()

        with toml_path.open("rb") as f:
            data = tomllib.load(f)

        port = int(data.get("port", 8080))
        master_key = str(data.get("master_key", "sk-llmwiki-local"))
        request_timeout = int(data.get("request_timeout", 600))
        rag_enabled = bool(data.get("rag_enabled", True))
        rag_top_k = int(data.get("rag_top_k", 5))
        rag_min_query_length = int(data.get("rag_min_query_length", 10))

        backends: dict[str, BackendConfig] = {}
        raw_backends = data.get("backends") or {}
        if isinstance(raw_backends, dict):
            for name, raw in raw_backends.items():
                if not isinstance(raw, dict):
                    continue
                api_base = str(raw.get("api_base", "")).strip()
                api_key = str(raw.get("api_key", ""))
                models_raw = raw.get("models") or DEFAULT_MODELS.get(name, [])
                models = [str(m) for m in models_raw if isinstance(m, str)]
                backends[name] = BackendConfig(
                    name=name,
                    api_base=api_base,
                    api_key=api_key,
                    models=models,
                )

        return cls(
            port=port,
            master_key=master_key,
            request_timeout=request_timeout,
            backends=backends,
            rag_enabled=rag_enabled,
            rag_top_k=rag_top_k,
            rag_min_query_length=rag_min_query_length,
        )

    def configured_backends(self) -> dict[str, BackendConfig]:
        return {n: b for n, b in self.backends.items() if b.api_base}


def write_default_template(vault_root: Path) -> tuple[Path, bool]:
    target = Path(vault_root) / CONFIG_FILENAME
    if target.exists():
        return target, False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(DEFAULT_TEMPLATE, encoding="utf-8")
    return target, True
