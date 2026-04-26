from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import httpx
import pytest

from llmwiki.imagen.client import (
    ImagenClient,
    ImagenError,
    ImagenTimeout,
    ImagenUnreachable,
)
from llmwiki.imagen.config import ImagenConfig


def _cfg(api_key: str = "sk-test", *, backend: str = "openai") -> ImagenConfig:
    return ImagenConfig(
        backend=backend,
        base_url="https://example.test/v1",
        api_key=api_key,
        model="opal/bananapro",
        size="1024x1024",
        timeout=10.0,
    )


def _gemini_cfg(api_key: str = "sk-test") -> ImagenConfig:
    return ImagenConfig(
        backend="gemini",
        base_url="https://example.test",
        api_key=api_key,
        model="opal/gemini-3-pro-image-preview",
        timeout=10.0,
    )


class _FakeResponse:
    def __init__(
        self,
        status_code: int,
        json_data: dict[str, Any] | None = None,
        content: bytes = b"",
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self._json = json_data
        self.content = content
        self.text = text or (str(json_data) if json_data else "")

    def json(self) -> dict[str, Any]:
        if self._json is None:
            raise ValueError("no json")
        return self._json


class _FakeClient:
    def __init__(
        self,
        post_response: _FakeResponse | Exception | None = None,
        get_responses: list[_FakeResponse] | None = None,
        get_exception: Exception | None = None,
    ) -> None:
        self._post_response = post_response
        self._get_responses = list(get_responses or [])
        self._get_exception = get_exception
        self.post_calls: list[dict[str, Any]] = []
        self.get_calls: list[str] = []

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> _FakeResponse:
        self.post_calls.append({"url": url, "json": json, "headers": headers})
        if isinstance(self._post_response, Exception):
            raise self._post_response
        assert self._post_response is not None
        return self._post_response

    def get(self, url: str) -> _FakeResponse:
        self.get_calls.append(url)
        if self._get_exception is not None:
            raise self._get_exception
        return self._get_responses.pop(0)


def _patch_client(monkeypatch: pytest.MonkeyPatch, fake: _FakeClient) -> None:
    def factory(*args: object, **kwargs: object) -> _FakeClient:
        return fake

    monkeypatch.setattr("llmwiki.imagen.client.httpx.Client", factory)


def test_empty_api_key_raises() -> None:
    with pytest.raises(ValueError, match="api_key is empty"):
        ImagenClient(_cfg(api_key=""))


def test_generate_url_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"data": [{"url": "https://cdn.test/img1.png"}]}
    img_bytes = b"\x89PNG\r\n\x1a\nfake"
    fake = _FakeClient(
        post_response=_FakeResponse(200, json_data=payload),
        get_responses=[_FakeResponse(200, content=img_bytes)],
    )
    _patch_client(monkeypatch, fake)

    client = ImagenClient(_cfg())
    out = tmp_path / "out"
    paths = client.generate("a cat", n=1, out_dir=out)

    assert len(paths) == 1
    assert paths[0].exists()
    assert paths[0].read_bytes() == img_bytes
    assert paths[0].suffix == ".png"
    assert fake.post_calls[0]["headers"]["Authorization"] == "Bearer sk-test"
    assert fake.post_calls[0]["json"]["model"] == "opal/bananapro"
    assert fake.post_calls[0]["json"]["prompt"] == "a cat"
    assert fake.post_calls[0]["json"]["n"] == 1
    assert fake.post_calls[0]["json"]["size"] == "1024x1024"
    assert fake.get_calls == ["https://cdn.test/img1.png"]


def test_generate_b64_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    raw = b"\x89PNG\r\n\x1a\nbytes"
    payload = {"data": [{"b64_json": base64.b64encode(raw).decode()}]}
    fake = _FakeClient(post_response=_FakeResponse(200, json_data=payload))
    _patch_client(monkeypatch, fake)

    client = ImagenClient(_cfg())
    out = tmp_path / "out"
    paths = client.generate("a dog", n=1, out_dir=out)

    assert len(paths) == 1
    assert paths[0].read_bytes() == raw
    assert fake.get_calls == []


def test_generate_n_three(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "data": [
            {"url": "https://cdn.test/a.png"},
            {"url": "https://cdn.test/b.png"},
            {"url": "https://cdn.test/c.png"},
        ]
    }
    fake = _FakeClient(
        post_response=_FakeResponse(200, json_data=payload),
        get_responses=[
            _FakeResponse(200, content=b"a"),
            _FakeResponse(200, content=b"b"),
            _FakeResponse(200, content=b"c"),
        ],
    )
    _patch_client(monkeypatch, fake)

    client = ImagenClient(_cfg())
    out = tmp_path / "multi"
    paths = client.generate("triple", n=3, out_dir=out)

    assert len(paths) == 3
    assert {p.read_bytes() for p in paths} == {b"a", b"b", b"c"}
    assert fake.post_calls[0]["json"]["n"] == 3


def test_unreachable_on_connect_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakeClient(post_response=httpx.ConnectError("nope"))
    _patch_client(monkeypatch, fake)
    client = ImagenClient(_cfg())
    with pytest.raises(ImagenUnreachable):
        client.generate("x", n=1, out_dir=tmp_path / "out")


def test_timeout_on_timeout_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakeClient(post_response=httpx.TimeoutException("slow"))
    _patch_client(monkeypatch, fake)
    client = ImagenClient(_cfg())
    with pytest.raises(ImagenTimeout):
        client.generate("x", n=1, out_dir=tmp_path / "out")


def test_imagen_error_on_5xx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient(post_response=_FakeResponse(503, json_data=None, text="upstream down"))
    _patch_client(monkeypatch, fake)
    client = ImagenClient(_cfg())
    with pytest.raises(ImagenError) as excinfo:
        client.generate("x", n=1, out_dir=tmp_path / "out")
    assert excinfo.value.status == 503


def test_imagen_error_on_empty_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakeClient(post_response=_FakeResponse(200, json_data={"data": []}))
    _patch_client(monkeypatch, fake)
    client = ImagenClient(_cfg())
    with pytest.raises(ImagenError, match="no images returned"):
        client.generate("x", n=1, out_dir=tmp_path / "out")


def test_imagen_error_on_missing_data_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakeClient(post_response=_FakeResponse(200, json_data={}))
    _patch_client(monkeypatch, fake)
    client = ImagenClient(_cfg())
    with pytest.raises(ImagenError, match="no images returned"):
        client.generate("x", n=1, out_dir=tmp_path / "out")


def test_invalid_backend_raises() -> None:
    cfg = ImagenConfig(backend="bogus", base_url="x", api_key="k", model="m")
    with pytest.raises(ValueError, match="must be 'gemini' or 'openai'"):
        ImagenClient(cfg)


def test_gemini_generate_inline_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = b"\xff\xd8\xff\xe0fake-jpeg"
    payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"inlineData": {"mimeType": "image/jpeg", "data": base64.b64encode(raw).decode()}}
                    ]
                }
            }
        ]
    }
    fake = _FakeClient(post_response=_FakeResponse(200, json_data=payload))
    _patch_client(monkeypatch, fake)

    client = ImagenClient(_gemini_cfg())
    paths = client.generate("a parrot", n=1, out_dir=tmp_path / "out")

    assert len(paths) == 1
    assert paths[0].suffix == ".jpg"
    assert paths[0].read_bytes() == raw
    # Gemini route uses x-goog-api-key, not Bearer
    assert fake.post_calls[0]["headers"]["x-goog-api-key"] == "sk-test"
    # URL contains :generateContent
    assert ":generateContent" in fake.post_calls[0]["url"]
    # body contains contents + responseModalities=IMAGE
    body = fake.post_calls[0]["json"]
    assert body["generationConfig"]["responseModalities"] == ["IMAGE"]
    assert body["contents"][0]["parts"][0]["text"] == "a parrot"


def test_gemini_n_three_issues_three_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = b"img"
    payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"inlineData": {"mimeType": "image/png", "data": base64.b64encode(raw).decode()}}
                    ]
                }
            }
        ]
    }

    class _MultiPostFake(_FakeClient):
        def __init__(self) -> None:
            super().__init__(post_response=_FakeResponse(200, json_data=payload))

        def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> _FakeResponse:
            self.post_calls.append({"url": url, "json": json, "headers": headers})
            return _FakeResponse(200, json_data=payload)

    fake = _MultiPostFake()
    _patch_client(monkeypatch, fake)
    client = ImagenClient(_gemini_cfg())
    paths = client.generate("triple", n=3, out_dir=tmp_path / "out")
    assert len(paths) == 3
    assert len(fake.post_calls) == 3


def test_gemini_no_inline_data_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = {
        "candidates": [
            {"content": {"parts": [{"text": "I cannot generate images."}]}}
        ]
    }
    fake = _FakeClient(post_response=_FakeResponse(200, json_data=payload))
    _patch_client(monkeypatch, fake)
    client = ImagenClient(_gemini_cfg())
    with pytest.raises(ImagenError, match="no inlineData"):
        client.generate("x", n=1, out_dir=tmp_path / "out")
