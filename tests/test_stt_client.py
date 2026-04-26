from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import httpx
import pytest

from llmwiki.stt.client import (
    WhisperClient,
    WhisperError,
    WhisperTimeout,
    WhisperUnreachable,
)
from llmwiki.stt.config import SttConfig


@pytest.fixture
def audio_file(tmp_path: Path) -> Path:
    p = tmp_path / "sample.wav"
    p.write_bytes(b"fake-audio-bytes")
    return p


def _install_handler(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> None:
    transport = httpx.MockTransport(handler)
    real_init = httpx.Client.__init__

    def fake_init(self: httpx.Client, *args: object, **kwargs: object) -> None:
        kwargs["transport"] = transport
        real_init(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx.Client, "__init__", fake_init)


def test_happy_path_parses_text_language_segments(
    monkeypatch: pytest.MonkeyPatch, audio_file: Path
) -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.content
        return httpx.Response(
            200,
            json={
                "text": "hello world",
                "language": "en",
                "segments": [
                    {"start": 0.0, "end": 1.5, "text": "hello"},
                    {"start": 1.5, "end": 3.2, "text": "world"},
                ],
            },
        )

    _install_handler(monkeypatch, handler)
    client = WhisperClient(SttConfig(whisper_base_url="http://x:9/"))
    transcript = client.transcribe(audio_file, language="en")

    assert transcript.text == "hello world"
    assert transcript.language == "en"
    assert len(transcript.segments) == 2
    assert transcript.duration == pytest.approx(3.2)
    assert captured["url"] == "http://x:9/transcribe"


def test_duration_none_when_no_segments(
    monkeypatch: pytest.MonkeyPatch, audio_file: Path
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"text": "x", "language": "en"})

    _install_handler(monkeypatch, handler)
    client = WhisperClient(SttConfig())
    transcript = client.transcribe(audio_file)
    assert transcript.duration is None
    assert transcript.segments == []


def test_unreachable_on_connect_error(
    monkeypatch: pytest.MonkeyPatch, audio_file: Path
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nope", request=request)

    _install_handler(monkeypatch, handler)
    client = WhisperClient(SttConfig())
    with pytest.raises(WhisperUnreachable):
        client.transcribe(audio_file)


def test_timeout_on_timeout_exception(
    monkeypatch: pytest.MonkeyPatch, audio_file: Path
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    _install_handler(monkeypatch, handler)
    client = WhisperClient(SttConfig())
    with pytest.raises(WhisperTimeout):
        client.transcribe(audio_file)


def test_http_error_on_5xx(
    monkeypatch: pytest.MonkeyPatch, audio_file: Path
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream down")

    _install_handler(monkeypatch, handler)
    client = WhisperClient(SttConfig())
    with pytest.raises(WhisperError) as excinfo:
        client.transcribe(audio_file)
    assert excinfo.value.status == 503
    assert "upstream down" in excinfo.value.body


def test_invalid_json_raises(
    monkeypatch: pytest.MonkeyPatch, audio_file: Path
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json")

    _install_handler(monkeypatch, handler)
    client = WhisperClient(SttConfig())
    with pytest.raises(WhisperError) as excinfo:
        client.transcribe(audio_file)
    assert "invalid JSON" in excinfo.value.body


@pytest.mark.parametrize("language", ["auto", "", None])
def test_auto_language_not_sent(
    monkeypatch: pytest.MonkeyPatch, audio_file: Path, language: str | None
) -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content.decode("utf-8", errors="replace")
        return httpx.Response(200, json={"text": "", "language": "en"})

    _install_handler(monkeypatch, handler)
    cfg = SttConfig(default_language="auto")
    client = WhisperClient(cfg)
    client.transcribe(audio_file, language=language)
    assert "name=\"language\"" not in captured["body"]


def test_explicit_language_sent(
    monkeypatch: pytest.MonkeyPatch, audio_file: Path
) -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content.decode("utf-8", errors="replace")
        return httpx.Response(200, json={"text": "x", "language": "zh"})

    _install_handler(monkeypatch, handler)
    client = WhisperClient(SttConfig())
    client.transcribe(audio_file, language="zh")
    assert "name=\"language\"" in captured["body"]
    assert "zh" in captured["body"]


def test_include_segments_toggle(
    monkeypatch: pytest.MonkeyPatch, audio_file: Path
) -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content.decode("utf-8", errors="replace")
        return httpx.Response(200, json={"text": "x", "language": "en"})

    _install_handler(monkeypatch, handler)
    client = WhisperClient(SttConfig())
    client.transcribe(audio_file, include_segments=False)
    assert "name=\"include_segments\"" in captured["body"]
    assert "false" in captured["body"]


def test_config_load_defaults(tmp_path: Path) -> None:
    cfg = SttConfig.load(tmp_path)
    assert cfg.whisper_base_url == "http://192.168.10.2:8000"
    assert cfg.default_language == "auto"
    assert cfg.timeout == 300.0


def test_config_load_from_toml(tmp_path: Path) -> None:
    (tmp_path / "stt.toml").write_text(
        'whisper_base_url = "http://h:1"\ndefault_language = "zh"\ntimeout = 60.0\n',
        encoding="utf-8",
    )
    cfg = SttConfig.load(tmp_path)
    assert cfg.whisper_base_url == "http://h:1"
    assert cfg.default_language == "zh"
    assert cfg.timeout == 60.0


def test_write_default_template_idempotent(tmp_path: Path) -> None:
    from llmwiki.stt.config import write_default_template

    target, written = write_default_template(tmp_path)
    assert written is True
    assert target.exists()
    body = target.read_text(encoding="utf-8")
    target2, written2 = write_default_template(tmp_path)
    assert written2 is False
    assert target2.read_text(encoding="utf-8") == body


def test_segments_with_non_dict_entries_filtered(
    monkeypatch: pytest.MonkeyPatch, audio_file: Path
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "text": "x",
                "language": "en",
                "segments": [{"end": 2.0}, "garbage", None],
            },
        )

    _install_handler(monkeypatch, handler)
    client = WhisperClient(SttConfig())
    transcript = client.transcribe(audio_file)
    assert len(transcript.segments) == 1
    assert transcript.duration == pytest.approx(2.0)


def test_segments_null_in_payload(
    monkeypatch: pytest.MonkeyPatch, audio_file: Path
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=json.dumps({"text": "x", "language": "en", "segments": None}),
            headers={"content-type": "application/json"},
        )

    _install_handler(monkeypatch, handler)
    client = WhisperClient(SttConfig())
    transcript = client.transcribe(audio_file)
    assert transcript.segments == []
    assert transcript.duration is None
