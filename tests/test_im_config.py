from __future__ import annotations

from pathlib import Path

import pytest

from llmwiki.im.config import ImConfig, write_default_template


def test_load_missing_returns_defaults(tmp_path: Path) -> None:
    cfg = ImConfig.load(tmp_path)
    assert cfg.http_port == 8081
    assert cfg.http_token is None
    assert cfg.default_tags == []
    assert cfg.url_fetch_enabled is True
    assert cfg.url_fetch_timeout == 30
    assert cfg.telegram.bot_token == ""
    assert cfg.telegram.allowed_user_ids == []
    assert cfg.telegram.command_default_tags == {}


def test_load_full_toml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLMWIKI_TG_TOKEN", raising=False)
    (tmp_path / "im.toml").write_text(
        """
http_port = 9999
http_token = "secret"
default_tags = ["task/inbox"]
url_fetch_enabled = false
url_fetch_timeout = 5

[telegram]
bot_token = "tg-token"
allowed_user_ids = [1, 2, 3]

[telegram.command_default_tags]
audio = ["task/audio"]
report = ["task/report"]
""",
        encoding="utf-8",
    )
    cfg = ImConfig.load(tmp_path)
    assert cfg.http_port == 9999
    assert cfg.http_token == "secret"
    assert cfg.default_tags == ["task/inbox"]
    assert cfg.url_fetch_enabled is False
    assert cfg.url_fetch_timeout == 5
    assert cfg.telegram.bot_token == "tg-token"
    assert cfg.telegram.allowed_user_ids == [1, 2, 3]
    assert cfg.telegram.command_default_tags == {
        "audio": ["task/audio"],
        "report": ["task/report"],
    }


def test_env_overrides_toml_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "im.toml").write_text(
        """
[telegram]
bot_token = "from-toml"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("LLMWIKI_TG_TOKEN", "from-env")
    cfg = ImConfig.load(tmp_path)
    assert cfg.telegram.bot_token == "from-env"


def test_write_default_template_idempotent(tmp_path: Path) -> None:
    target, written = write_default_template(tmp_path)
    assert target.exists()
    assert written is True
    target2, written2 = write_default_template(tmp_path)
    assert target2 == target
    assert written2 is False
