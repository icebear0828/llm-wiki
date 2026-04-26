from __future__ import annotations

from pathlib import Path

import frontmatter
import pytest

from llmwiki.im import common
from llmwiki.im.common import IncomingMessage, ingest, slugify
from llmwiki.im.config import ImConfig
from llmwiki.vault import Vault


@pytest.fixture()
def vault(tmp_path: Path) -> Vault:
    root = tmp_path / "vault"
    (root / "raw").mkdir(parents=True)
    (root / "wiki").mkdir(parents=True)
    return Vault(root=root)


@pytest.fixture()
def cfg() -> ImConfig:
    return ImConfig(default_tags=["task/inbox"])


def _load(path: Path) -> frontmatter.Post:
    return frontmatter.load(str(path))


def test_slugify_edges() -> None:
    assert slugify("") == "msg"
    assert slugify("   ") == "msg"
    assert slugify("Hello World!") == "hello-world"
    assert slugify("---***---") == "msg"
    assert slugify("中文 hello") == "hello"
    long = slugify("a" * 100)
    assert len(long) <= 40


def test_ingest_text(vault: Vault, cfg: ImConfig) -> None:
    msg = IncomingMessage(kind="text", text="Hello world this is a note", source="http", tags=["task/extra"])
    path = ingest(msg, vault, cfg)
    assert path.exists()
    assert path.parent == vault.raw
    post = _load(path)
    assert post.metadata["title"] == "Hello world this is a note"
    assert post.metadata["status"] == "pending"
    assert post.metadata["source"] == "http"
    assert "created" in post.metadata
    assert post.metadata["tags"] == ["task/inbox", "task/extra"]
    assert "Hello world this is a note" in post.content


def test_ingest_text_title_override(vault: Vault, cfg: ImConfig) -> None:
    msg = IncomingMessage(kind="text", text="body here", title="Custom Title")
    path = ingest(msg, vault, cfg)
    post = _load(path)
    assert post.metadata["title"] == "Custom Title"


def test_ingest_url_success(monkeypatch: pytest.MonkeyPatch, vault: Vault, cfg: ImConfig) -> None:
    monkeypatch.setattr(common, "_fetch_url_markdown", lambda url, timeout: ("# Title\n\nbody text", None))
    msg = IncomingMessage(kind="url", url="https://example.com/article", source="http")
    path = ingest(msg, vault, cfg)
    post = _load(path)
    assert post.metadata["source_url"] == "https://example.com/article"
    assert "# Title" in post.content
    assert "Source: https://example.com/article" in post.content


def test_ingest_url_fetch_returns_none(monkeypatch: pytest.MonkeyPatch, vault: Vault, cfg: ImConfig) -> None:
    monkeypatch.setattr(common, "_fetch_url_markdown", lambda url, timeout: (None, "fetch returned no content"))
    msg = IncomingMessage(kind="url", url="https://bad.example/x")
    path = ingest(msg, vault, cfg)
    post = _load(path)
    assert "Source: https://bad.example/x" in post.content
    assert "fetch failed" in post.content


def test_ingest_url_fetch_raises(monkeypatch: pytest.MonkeyPatch, vault: Vault, cfg: ImConfig) -> None:
    def _boom(url: str, timeout: int) -> tuple[str | None, str | None]:
        raise RuntimeError("boom")

    monkeypatch.setattr(common, "_fetch_url_markdown", _boom)
    msg = IncomingMessage(kind="url", url="https://bad.example/x")
    with pytest.raises(RuntimeError):
        ingest(msg, vault, cfg)


def test_ingest_url_disabled(vault: Vault) -> None:
    cfg = ImConfig(url_fetch_enabled=False)
    msg = IncomingMessage(kind="url", url="https://example.com/x")
    path = ingest(msg, vault, cfg)
    post = _load(path)
    assert "Source: https://example.com/x" in post.content


def test_ingest_file(vault: Vault, cfg: ImConfig, tmp_path: Path) -> None:
    src = tmp_path / "audio.mp3"
    src.write_bytes(b"\x00\x01\x02 fake mp3")
    msg = IncomingMessage(kind="file", file_path=src, tags=["task/audio"])
    path = ingest(msg, vault, cfg)
    post = _load(path)
    assert "source_file" in post.metadata
    src_file = str(post.metadata["source_file"])
    assert src_file.startswith("raw/")
    assert src_file.endswith("audio.mp3")
    assert (vault.root / src_file).is_file()
    assert (vault.root / src_file).read_bytes() == b"\x00\x01\x02 fake mp3"
    assert "![[" in post.content


def test_ingest_voice_default_tag(vault: Vault, cfg: ImConfig, tmp_path: Path) -> None:
    src = tmp_path / "speech.ogg"
    src.write_bytes(b"oggdata")
    msg = IncomingMessage(kind="voice", voice_path=src)
    path = ingest(msg, vault, cfg)
    post = _load(path)
    tags = post.metadata.get("tags") or []
    assert "task/voice" in tags
    assert "task/inbox" in tags


def test_tag_dedup(vault: Vault) -> None:
    cfg = ImConfig(default_tags=["a", "b"])
    msg = IncomingMessage(kind="text", text="hi", tags=["b", "c", "a"])
    path = ingest(msg, vault, cfg)
    post = _load(path)
    assert post.metadata["tags"] == ["a", "b", "c"]


def test_filename_format(vault: Vault, cfg: ImConfig) -> None:
    msg = IncomingMessage(kind="text", text="quick brown fox jumps over the lazy dog")
    path = ingest(msg, vault, cfg)
    parts = path.stem.split("-")
    assert len(parts[0]) == 8  # YYYYMMDD
    assert path.suffix == ".md"
