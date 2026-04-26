from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from llmwiki.im import notify
from llmwiki.im.config import TelegramConfig


class _FakeResponse:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code


class _FakeHttpx:
    def __init__(self, response: _FakeResponse | None = None, raise_exc: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._response = response or _FakeResponse(200)
        self._raise = raise_exc

    def post(self, url: str, *, json: dict[str, Any] | None = None, timeout: int = 10) -> _FakeResponse:
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        if self._raise is not None:
            raise self._raise
        return self._response


def test_no_token_skips_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeHttpx()
    monkeypatch.setattr(notify, "httpx", fake)
    cfg = TelegramConfig(bot_token="", notify_chat_id=12345)
    notify.push_telegram("hi", cfg=cfg, vault_root=tmp_path)
    assert fake.calls == []


def test_no_chat_id_skips_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeHttpx()
    monkeypatch.setattr(notify, "httpx", fake)
    cfg = TelegramConfig(bot_token="abc", notify_chat_id=None)
    notify.push_telegram("hi", cfg=cfg, vault_root=tmp_path)
    assert fake.calls == []


def test_successful_call_records_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeHttpx()
    monkeypatch.setattr(notify, "httpx", fake)
    cfg = TelegramConfig(bot_token="TOKEN123", notify_chat_id=99)
    notify.push_telegram("hello", cfg=cfg, vault_root=tmp_path, throttle_key="k1")

    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert "TOKEN123" in call["url"]
    assert "sendMessage" in call["url"]
    assert call["json"] == {"chat_id": 99, "text": "hello"}

    state_file = tmp_path / ".llmwiki" / "notify-state.json"
    assert state_file.exists()
    data = json.loads(state_file.read_text(encoding="utf-8"))
    assert "k1" in data


def test_throttle_skips_within_window(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeHttpx()
    monkeypatch.setattr(notify, "httpx", fake)
    cfg = TelegramConfig(bot_token="TOKEN", notify_chat_id=42)

    notify.push_telegram("first", cfg=cfg, vault_root=tmp_path, throttle_key="same", window_seconds=3600)
    notify.push_telegram("second", cfg=cfg, vault_root=tmp_path, throttle_key="same", window_seconds=3600)

    assert len(fake.calls) == 1


def test_throttle_different_keys_both_send(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeHttpx()
    monkeypatch.setattr(notify, "httpx", fake)
    cfg = TelegramConfig(bot_token="TOKEN", notify_chat_id=42)

    notify.push_telegram("a", cfg=cfg, vault_root=tmp_path, throttle_key="key-a")
    notify.push_telegram("b", cfg=cfg, vault_root=tmp_path, throttle_key="key-b")

    assert len(fake.calls) == 2


def test_throttle_outside_window_resends(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeHttpx()
    monkeypatch.setattr(notify, "httpx", fake)
    cfg = TelegramConfig(bot_token="TOKEN", notify_chat_id=42)

    state_dir = tmp_path / ".llmwiki"
    state_dir.mkdir()
    old_ts = (dt.datetime.now(dt.UTC) - dt.timedelta(seconds=7200)).isoformat()
    (state_dir / "notify-state.json").write_text(json.dumps({"k": old_ts}), encoding="utf-8")

    notify.push_telegram("again", cfg=cfg, vault_root=tmp_path, throttle_key="k", window_seconds=3600)
    assert len(fake.calls) == 1


def test_httpx_exception_swallowed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeHttpx(raise_exc=RuntimeError("net down"))
    monkeypatch.setattr(notify, "httpx", fake)
    cfg = TelegramConfig(bot_token="TOKEN", notify_chat_id=42)

    # Should not raise
    notify.push_telegram("x", cfg=cfg, vault_root=tmp_path, throttle_key="k")

    state_file = tmp_path / ".llmwiki" / "notify-state.json"
    assert not state_file.exists()


def test_non_200_does_not_record_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeHttpx(response=_FakeResponse(status_code=500))
    monkeypatch.setattr(notify, "httpx", fake)
    cfg = TelegramConfig(bot_token="TOKEN", notify_chat_id=42)

    notify.push_telegram("x", cfg=cfg, vault_root=tmp_path, throttle_key="k")
    state_file = tmp_path / ".llmwiki" / "notify-state.json"
    assert not state_file.exists()
