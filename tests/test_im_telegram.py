from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from llmwiki.im import telegram_bot as tg_mod
from llmwiki.im.config import ImConfig, TelegramConfig
from llmwiki.im.telegram_bot import TelegramBot, _is_url
from llmwiki.vault import Vault


@pytest.fixture()
def vault(tmp_path: Path) -> Vault:
    root = tmp_path / "vault"
    (root / "raw").mkdir(parents=True)
    (root / "wiki").mkdir(parents=True)
    return Vault(root=root)


@pytest.fixture()
def cfg_open() -> ImConfig:
    return ImConfig(telegram=TelegramConfig(bot_token="test:token"))


@pytest.fixture()
def cfg_with_whitelist() -> ImConfig:
    return ImConfig(
        telegram=TelegramConfig(bot_token="test:token", allowed_user_ids=[42])
    )


@pytest.fixture()
def cfg_with_command_tags() -> ImConfig:
    return ImConfig(
        telegram=TelegramConfig(
            bot_token="test:token",
            command_default_tags={"audio": ["lang/en"]},
        )
    )


def _make_update(
    *,
    user_id: int | None = 42,
    text: str | None = None,
    document: object | None = None,
    photo: list[object] | None = None,
    voice: object | None = None,
) -> tuple[MagicMock, MagicMock]:
    message = MagicMock()
    message.text = text
    message.document = document
    message.photo = photo or []
    message.voice = voice
    message.reply_text = AsyncMock()

    user = MagicMock()
    user.id = user_id

    update = MagicMock()
    update.effective_message = message
    update.effective_user = user
    return update, message


def _ctx(args: list[str] | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.args = args
    return ctx


def test_is_url_detection() -> None:
    assert _is_url("https://example.com")
    assert _is_url("http://example.com/path?x=1")
    assert not _is_url("hello https://example.com world")
    assert not _is_url("just text")
    assert not _is_url("")
    assert not _is_url("ftp://example.com")


def test_constructor_requires_token(vault: Vault) -> None:
    with pytest.raises(ValueError, match="bot_token"):
        TelegramBot(vault, ImConfig())


def test_text_message_ingests_as_text(
    vault: Vault, cfg_open: ImConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    def fake_ingest(msg, v, c):  # type: ignore[no-untyped-def]
        captured["msg"] = msg
        return vault.raw / "out.md"

    monkeypatch.setattr(tg_mod, "ingest", fake_ingest)
    bot = TelegramBot(vault, cfg_open)
    update, message = _make_update(text="hello world")

    import asyncio

    asyncio.run(bot.handle_text(update, _ctx()))

    assert captured["msg"].kind == "text"
    assert captured["msg"].text == "hello world"
    assert captured["msg"].source.startswith("telegram:")
    message.reply_text.assert_awaited_once()
    assert "ingested" in message.reply_text.await_args.args[0]


def test_url_message_ingests_as_url(
    vault: Vault, cfg_open: ImConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}
    def _fake(msg: Any, _v: Any, _c: Any) -> Path:
        captured["msg"] = msg
        return vault.raw / "x.md"

    monkeypatch.setattr(tg_mod, "ingest", _fake)
    bot = TelegramBot(vault, cfg_open)
    update, _msg = _make_update(text="https://example.com/page")

    import asyncio

    asyncio.run(bot.handle_text(update, _ctx()))

    assert captured["msg"].kind == "url"
    assert captured["msg"].url == "https://example.com/page"


def test_text_with_url_inline_stays_text(
    vault: Vault, cfg_open: ImConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}
    def _fake(msg: Any, _v: Any, _c: Any) -> Path:
        captured["msg"] = msg
        return vault.raw / "x.md"

    monkeypatch.setattr(tg_mod, "ingest", _fake)
    bot = TelegramBot(vault, cfg_open)
    update, _msg = _make_update(text="check this https://example.com out")

    import asyncio

    asyncio.run(bot.handle_text(update, _ctx()))

    assert captured["msg"].kind == "text"


def test_audio_command_with_url(
    vault: Vault, cfg_open: ImConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}
    def _fake(msg: Any, _v: Any, _c: Any) -> Path:
        captured["msg"] = msg
        return vault.raw / "x.md"

    monkeypatch.setattr(tg_mod, "ingest", _fake)
    bot = TelegramBot(vault, cfg_open)
    handler = bot._make_task_handler("audio")
    update, _msg = _make_update(text="/audio https://example.com/foo")

    import asyncio

    asyncio.run(handler(update, _ctx(args=["https://example.com/foo"])))

    assert captured["msg"].kind == "url"
    assert captured["msg"].url == "https://example.com/foo"
    assert captured["msg"].tags == ["task/audio"]


def test_report_command_with_text(
    vault: Vault, cfg_open: ImConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}
    def _fake(msg: Any, _v: Any, _c: Any) -> Path:
        captured["msg"] = msg
        return vault.raw / "x.md"

    monkeypatch.setattr(tg_mod, "ingest", _fake)
    bot = TelegramBot(vault, cfg_open)
    handler = bot._make_task_handler("report")
    update, _msg = _make_update(text="/report some text body here")

    import asyncio

    asyncio.run(handler(update, _ctx(args=["some", "text", "body", "here"])))

    assert captured["msg"].kind == "text"
    assert captured["msg"].text == "some text body here"
    assert captured["msg"].tags == ["task/report"]


def test_command_default_tags_merged(
    vault: Vault, cfg_with_command_tags: ImConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}
    def _fake(msg: Any, _v: Any, _c: Any) -> Path:
        captured["msg"] = msg
        return vault.raw / "x.md"

    monkeypatch.setattr(tg_mod, "ingest", _fake)
    bot = TelegramBot(vault, cfg_with_command_tags)
    handler = bot._make_task_handler("audio")
    update, _msg = _make_update(text="/audio hi")

    import asyncio

    asyncio.run(handler(update, _ctx(args=["hi"])))

    assert "task/audio" in captured["msg"].tags
    assert "lang/en" in captured["msg"].tags


def test_note_command_text_only(
    vault: Vault, cfg_open: ImConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}
    def _fake(msg: Any, _v: Any, _c: Any) -> Path:
        captured["msg"] = msg
        return vault.raw / "x.md"

    monkeypatch.setattr(tg_mod, "ingest", _fake)
    bot = TelegramBot(vault, cfg_open)
    update, _msg = _make_update(text="/note quick thought")

    import asyncio

    asyncio.run(bot.handle_note(update, _ctx(args=["quick", "thought"])))

    assert captured["msg"].kind == "text"
    assert captured["msg"].text == "quick thought"
    assert captured["msg"].tags == []


def test_document_message(
    vault: Vault, cfg_open: ImConfig, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, Any] = {}
    def _fake(msg: Any, _v: Any, _c: Any) -> Path:
        captured["msg"] = msg
        return vault.raw / "x.md"

    monkeypatch.setattr(tg_mod, "ingest", _fake)

    async def fake_download(custom_path: str) -> None:
        Path(custom_path).write_bytes(b"document content")

    tg_file = MagicMock()
    tg_file.download_to_drive = AsyncMock(side_effect=fake_download)

    document = MagicMock()
    document.file_name = "report.pdf"
    document.get_file = AsyncMock(return_value=tg_file)

    bot = TelegramBot(vault, cfg_open)
    update, _msg = _make_update(document=document)

    import asyncio

    asyncio.run(bot.handle_document(update, _ctx()))

    assert captured["msg"].kind == "file"
    assert captured["msg"].file_path is not None
    assert captured["msg"].file_path.exists()
    assert captured["msg"].title == "report.pdf"


def test_voice_message_adds_transcribe_tag(
    vault: Vault, cfg_open: ImConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}
    def _fake(msg: Any, _v: Any, _c: Any) -> Path:
        captured["msg"] = msg
        return vault.raw / "x.md"

    monkeypatch.setattr(tg_mod, "ingest", _fake)

    async def fake_download(custom_path: str) -> None:
        Path(custom_path).write_bytes(b"voice content")

    tg_file = MagicMock()
    tg_file.download_to_drive = AsyncMock(side_effect=fake_download)
    voice = MagicMock()
    voice.get_file = AsyncMock(return_value=tg_file)

    bot = TelegramBot(vault, cfg_open)
    update, _msg = _make_update(voice=voice)

    import asyncio

    asyncio.run(bot.handle_voice(update, _ctx()))

    assert captured["msg"].kind == "voice"
    assert captured["msg"].voice_path is not None
    assert captured["msg"].voice_path.suffix == ".ogg"
    assert "task/transcribe" in captured["msg"].tags
    assert "task/voice" not in captured["msg"].tags


def test_unauthorized_user_rejected(
    vault: Vault, cfg_with_whitelist: ImConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: dict[str, bool] = {"ingested": False}

    def fake_ingest(*_args: object, **_kwargs: object) -> Path:
        called["ingested"] = True
        return vault.raw / "x.md"

    monkeypatch.setattr(tg_mod, "ingest", fake_ingest)
    bot = TelegramBot(vault, cfg_with_whitelist)
    update, message = _make_update(user_id=999, text="hi")

    import asyncio

    asyncio.run(bot.handle_text(update, _ctx()))

    assert not called["ingested"]
    message.reply_text.assert_awaited_once_with("unauthorized")


def test_open_default_accepts_anyone(
    vault: Vault, cfg_open: ImConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: dict[str, bool] = {"ingested": False}

    def fake_ingest(*_args: object, **_kwargs: object) -> Path:
        called["ingested"] = True
        return vault.raw / "x.md"

    monkeypatch.setattr(tg_mod, "ingest", fake_ingest)
    bot = TelegramBot(vault, cfg_open)
    update, _msg = _make_update(user_id=12345, text="hi")

    import asyncio

    asyncio.run(bot.handle_text(update, _ctx()))

    assert called["ingested"]


def test_ingest_exception_replies_error_does_not_crash(
    vault: Vault, cfg_open: ImConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_args: object, **_kwargs: object) -> Path:
        raise RuntimeError("disk full")

    monkeypatch.setattr(tg_mod, "ingest", boom)
    bot = TelegramBot(vault, cfg_open)
    update, message = _make_update(text="hi")

    import asyncio

    asyncio.run(bot.handle_text(update, _ctx()))

    message.reply_text.assert_awaited_once()
    reply = message.reply_text.await_args.args[0]
    assert "ingest failed" in reply
    assert "disk full" in reply


def test_help_command_no_ingest(
    vault: Vault, cfg_open: ImConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: dict[str, bool] = {"ingested": False}

    def fake_ingest(*_args: object, **_kwargs: object) -> Path:
        called["ingested"] = True
        return vault.raw / "x.md"

    monkeypatch.setattr(tg_mod, "ingest", fake_ingest)
    bot = TelegramBot(vault, cfg_open)
    update, message = _make_update(text="/help")

    import asyncio

    asyncio.run(bot.handle_help(update, _ctx()))

    assert not called["ingested"]
    message.reply_text.assert_awaited_once()


def test_build_application_registers_handlers(vault: Vault, cfg_open: ImConfig) -> None:
    bot = TelegramBot(vault, cfg_open)
    application = bot.build_application()
    handlers = [h for group in application.handlers.values() for h in group]
    assert handlers, "handlers should be registered"
