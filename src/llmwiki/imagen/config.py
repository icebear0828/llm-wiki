from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

CONFIG_FILENAME = "imagen.toml"

# Local imagen config — fill in your own gateway / api key. Not committed to git.
# api_key may be set here or via env LLMWIKI_IMAGEN_KEY (recommended for CI/Docker).
DEFAULT_TEMPLATE = """\
backend = "gemini"
base_url = ""
api_key = ""
model = "opal/gemini-3-pro-image-preview"
output_subdir = "assets/images"
size = "1024x1024"
timeout = 300.0
"""


@dataclass(frozen=True)
class ImagenConfig:
    backend: str = "gemini"      # "gemini" (Google /v1beta) or "openai" (/v1/images/generations)
    base_url: str = ""
    api_key: str = ""
    model: str = "opal/gemini-3-pro-image-preview"
    output_subdir: str = "assets/images"
    size: str = "1024x1024"
    timeout: float = 300.0

    @classmethod
    def load(cls, vault_root: Path) -> "ImagenConfig":
        toml_path = Path(vault_root) / CONFIG_FILENAME
        data: dict[str, object] = {}
        if toml_path.is_file():
            with toml_path.open("rb") as f:
                data = tomllib.load(f)

        backend = str(data.get("backend", "gemini"))
        base_url = str(data.get("base_url", ""))
        api_key = str(data.get("api_key", "") or "")
        model = str(data.get("model", "opal/gemini-3-pro-image-preview"))
        output_subdir = str(data.get("output_subdir", "assets/images"))
        size = str(data.get("size", "1024x1024"))
        timeout = float(data.get("timeout", 300.0))  # type: ignore[arg-type]

        env_key = os.environ.get("LLMWIKI_IMAGEN_KEY", "")
        if env_key:
            api_key = env_key

        return cls(
            backend=backend,
            base_url=base_url,
            api_key=api_key,
            model=model,
            output_subdir=output_subdir,
            size=size,
            timeout=timeout,
        )


def write_default_template(vault_root: Path) -> tuple[Path, bool]:
    target = Path(vault_root) / CONFIG_FILENAME
    if target.exists():
        return target, False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(DEFAULT_TEMPLATE, encoding="utf-8")
    return target, True
