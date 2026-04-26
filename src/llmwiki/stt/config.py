from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

CONFIG_FILENAME = "stt.toml"

DEFAULT_TEMPLATE = """\
whisper_base_url = "http://192.168.10.2:8000"
default_language = "auto"
timeout = 300.0
"""


@dataclass(frozen=True)
class SttConfig:
    whisper_base_url: str = "http://192.168.10.2:8000"
    default_language: str = "auto"
    timeout: float = 300.0

    @classmethod
    def load(cls, vault_root: Path) -> "SttConfig":
        toml_path = Path(vault_root) / CONFIG_FILENAME
        if not toml_path.is_file():
            return cls()
        with toml_path.open("rb") as f:
            data = tomllib.load(f)
        return cls(
            whisper_base_url=str(data.get("whisper_base_url", cls.whisper_base_url)),
            default_language=str(data.get("default_language", cls.default_language)),
            timeout=float(data.get("timeout", cls.timeout)),
        )


def write_default_template(vault_root: Path) -> tuple[Path, bool]:
    target = Path(vault_root) / CONFIG_FILENAME
    if target.exists():
        return target, False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(DEFAULT_TEMPLATE, encoding="utf-8")
    return target, True
