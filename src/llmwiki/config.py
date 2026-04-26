from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path


@dataclass(frozen=True)
class Config:
    vault_root: Path
    debounce_seconds: float = 5.0
    notecraft_timeout: float = 600.0

    @classmethod
    def load(cls, vault_root: Path | None = None) -> "Config":
        if vault_root is not None:
            root = Path(vault_root).resolve()
        elif os.environ.get("LLMWIKI_VAULT"):
            root = Path(os.environ["LLMWIKI_VAULT"]).resolve()
        else:
            try:
                from llmwiki.vault import Vault  # type: ignore[import-not-found]

                root = Vault.discover().root  # type: ignore[attr-defined]
            except Exception:
                root = Path.cwd().resolve()

        cfg = cls(vault_root=root)
        toml_path = root / "config.toml"
        if toml_path.is_file():
            with toml_path.open("rb") as f:
                data = tomllib.load(f)
            updates: dict[str, float] = {}
            if "debounce_seconds" in data:
                updates["debounce_seconds"] = float(data["debounce_seconds"])
            if "notecraft_timeout" in data:
                updates["notecraft_timeout"] = float(data["notecraft_timeout"])
            if updates:
                cfg = replace(cfg, **updates)
        return cfg
