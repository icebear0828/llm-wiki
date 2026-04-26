from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_FILENAME = "im.toml"

DEFAULT_TEMPLATE = """\
http_port = 8081
# http_token = "<random>"   # uncomment to require X-Llmwiki-Token header
default_tags = []
url_fetch_enabled = true
url_fetch_timeout = 30

[telegram]
bot_token = ""               # or set env LLMWIKI_TG_TOKEN
allowed_user_ids = []        # whitelist; empty = anyone
[telegram.command_default_tags]
# audio = ["task/audio"]
# report = ["task/report"]
"""


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str = ""
    allowed_user_ids: list[int] = field(default_factory=list)
    command_default_tags: dict[str, list[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class ImConfig:
    http_port: int = 8081
    http_token: str | None = None
    default_tags: list[str] = field(default_factory=list)
    url_fetch_enabled: bool = True
    url_fetch_timeout: int = 30
    telegram: TelegramConfig = field(default_factory=TelegramConfig)

    @classmethod
    def load(cls, vault_root: Path) -> "ImConfig":
        toml_path = Path(vault_root) / CONFIG_FILENAME
        data: dict[str, object] = {}
        if toml_path.is_file():
            with toml_path.open("rb") as f:
                data = tomllib.load(f)

        http_port = int(_get(data, "http_port", 8081))
        http_token_raw = data.get("http_token")
        http_token = str(http_token_raw) if isinstance(http_token_raw, str) and http_token_raw else None

        default_tags_raw = data.get("default_tags") or []
        default_tags = [str(t) for t in default_tags_raw if isinstance(t, (str, int))] if isinstance(default_tags_raw, list) else []

        url_fetch_enabled = bool(_get(data, "url_fetch_enabled", True))
        url_fetch_timeout = int(_get(data, "url_fetch_timeout", 30))

        tg_raw = data.get("telegram") or {}
        if not isinstance(tg_raw, dict):
            tg_raw = {}

        bot_token = str(tg_raw.get("bot_token", "") or "")
        env_token = os.environ.get("LLMWIKI_TG_TOKEN", "")
        if env_token:
            bot_token = env_token

        allowed_raw = tg_raw.get("allowed_user_ids") or []
        allowed_ids: list[int] = []
        if isinstance(allowed_raw, list):
            for x in allowed_raw:
                try:
                    allowed_ids.append(int(x))
                except (TypeError, ValueError):
                    continue

        cmd_tags_raw = tg_raw.get("command_default_tags") or {}
        command_default_tags: dict[str, list[str]] = {}
        if isinstance(cmd_tags_raw, dict):
            for k, v in cmd_tags_raw.items():
                if isinstance(v, list):
                    command_default_tags[str(k)] = [str(x) for x in v if isinstance(x, (str, int))]

        telegram = TelegramConfig(
            bot_token=bot_token,
            allowed_user_ids=allowed_ids,
            command_default_tags=command_default_tags,
        )

        return cls(
            http_port=http_port,
            http_token=http_token,
            default_tags=default_tags,
            url_fetch_enabled=url_fetch_enabled,
            url_fetch_timeout=url_fetch_timeout,
            telegram=telegram,
        )


def _get(data: dict[str, object], key: str, default: object) -> object:
    value = data.get(key)
    return default if value is None else value


def write_default_template(vault_root: Path) -> tuple[Path, bool]:
    target = Path(vault_root) / CONFIG_FILENAME
    if target.exists():
        return target, False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(DEFAULT_TEMPLATE, encoding="utf-8")
    return target, True
