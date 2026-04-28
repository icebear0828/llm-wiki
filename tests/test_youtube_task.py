from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from llmwiki import notecraft
from llmwiki.tasks import youtube
from llmwiki.vault import Note


_SAMPLE_OEMBED = {
    "title": "Sample YouTube Video",
    "author_name": "Sample Channel",
    "author_url": "https://www.youtube.com/@sample",
    "thumbnail_url": "https://i.ytimg.com/vi/tj8ggd8UvB0/hqdefault.jpg",
    "type": "video",
}


def _make_vault(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    (tmp_path / "raw").mkdir()
    (tmp_path / "wiki").mkdir()
    (tmp_path / "assets").mkdir()
    return tmp_path


def _make_note(vault: Path, frontmatter: str, body: str = "stub\n") -> Note:
    p = vault / "raw" / "n.md"
    p.write_text(f"---\n{frontmatter}---\n{body}", encoding="utf-8")
    return Note(p)


# ---------- ID parsing ----------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("tj8ggd8UvB0", "tj8ggd8UvB0"),
        ("https://www.youtube.com/watch?v=tj8ggd8UvB0", "tj8ggd8UvB0"),
        ("https://www.youtube.com/watch?v=tj8ggd8UvB0&t=42s", "tj8ggd8UvB0"),
        ("https://youtu.be/tj8ggd8UvB0", "tj8ggd8UvB0"),
        ("https://youtu.be/tj8ggd8UvB0?t=42", "tj8ggd8UvB0"),
        ("https://www.youtube.com/shorts/tj8ggd8UvB0", "tj8ggd8UvB0"),
        ("https://www.youtube.com/embed/tj8ggd8UvB0", "tj8ggd8UvB0"),
        ("https://m.youtube.com/watch?v=tj8ggd8UvB0", "tj8ggd8UvB0"),
        ("youtube:tj8ggd8UvB0", "tj8ggd8UvB0"),
        # underscore + dash should be valid in id (must be 11 chars)
        ("https://youtu.be/abc_-XYZ123", "abc_-XYZ123"),
    ],
)
def test_parse_video_id(raw: str, expected: str) -> None:
    assert youtube._parse_video_id(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "not a url",
        "https://example.com/foo",
        "tj8ggd8UvB0extra",  # 12+ chars: overmatch trap
        "tj8ggd8UvB",  # 10 chars: too short
        "https://youtu.be/short!id$",  # invalid chars
        "",
    ],
)
def test_parse_video_id_rejects_garbage_and_overmatch(raw: str) -> None:
    with pytest.raises(notecraft.NotecraftError):
        youtube._parse_video_id(raw)


@pytest.mark.parametrize(
    "raw",
    [
        # Non-YouTube hosts must NOT yield an id even if their path/query
        # contains an 11-char base64url-ish slug — id alphabet is too generic.
        "https://example.com/?v=tj8ggd8UvB0",
        "https://github.com/owner/abcdefghijk",
        "https://github.com/icebear0828/llm-wiki/issues/53",
        "https://malicious.example.com/watch?v=tj8ggd8UvB0",
        "https://example.com/embed/tj8ggd8UvB0",
    ],
)
def test_parse_video_id_rejects_non_youtube_hosts(raw: str) -> None:
    with pytest.raises(notecraft.NotecraftError):
        youtube._parse_video_id(raw)


@pytest.mark.parametrize(
    "raw,expected",
    [
        # YouTube subdomain variants must work
        ("https://music.youtube.com/watch?v=tj8ggd8UvB0", "tj8ggd8UvB0"),
        ("https://www.youtube-nocookie.com/embed/tj8ggd8UvB0", "tj8ggd8UvB0"),
    ],
)
def test_parse_video_id_accepts_youtube_subdomains(raw: str, expected: str) -> None:
    assert youtube._parse_video_id(raw) == expected


# ---------- ID resolution priority ----------

def test_resolve_id_arg_wins(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    note = _make_note(
        vault,
        "title: T\nyoutube_id: aaaaaaaaaaa\nsource: https://youtu.be/bbbbbbbbbbb\n",
    )
    assert youtube._resolve_video_id(note, "tj8ggd8UvB0") == "tj8ggd8UvB0"


def test_resolve_id_frontmatter_used(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    note = _make_note(vault, "title: T\nyoutube_id: tj8ggd8UvB0\n")
    assert youtube._resolve_video_id(note, None) == "tj8ggd8UvB0"


def test_resolve_id_from_source_url(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    note = _make_note(vault, "title: T\nsource: https://www.youtube.com/watch?v=tj8ggd8UvB0\n")
    assert youtube._resolve_video_id(note, None) == "tj8ggd8UvB0"


def test_resolve_id_missing_raises(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    note = _make_note(vault, "title: T\n")
    with pytest.raises(notecraft.NotecraftError):
        youtube._resolve_video_id(note, None)


def test_resolve_id_falls_through_bad_frontmatter_to_source_url(tmp_path: Path) -> None:
    """If `youtube_id:` frontmatter is unparseable, fall back to source URL."""
    vault = _make_vault(tmp_path)
    note = _make_note(
        vault,
        "title: T\nyoutube_id: 'not a real id'\nsource: https://www.youtube.com/watch?v=tj8ggd8UvB0\n",
    )
    assert youtube._resolve_video_id(note, None) == "tj8ggd8UvB0"


def test_resolve_id_skips_non_youtube_source_url(tmp_path: Path) -> None:
    """source URL with 11-char slug from non-YouTube host must NOT be picked up."""
    vault = _make_vault(tmp_path)
    note = _make_note(
        vault, "title: T\nsource: https://github.com/owner/abcdefghijk\n"
    )
    with pytest.raises(notecraft.NotecraftError):
        youtube._resolve_video_id(note, None)


# ---------- HTTP fakes ----------

class _FakeResp:
    def __init__(self, *, status_code: int = 200, text: str = "", content: bytes = b"") -> None:
        self.status_code = status_code
        self.text = text
        self.content = content

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


# ---------- oembed fetch ----------

def test_fetch_oembed_parses_json(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_get(url: str, *, timeout: float = 10.0) -> _FakeResp:
        captured["url"] = url
        return _FakeResp(text=json.dumps(_SAMPLE_OEMBED))

    monkeypatch.setattr(youtube, "_http_get", fake_get)
    meta = youtube._fetch_oembed("tj8ggd8UvB0")
    assert "tj8ggd8UvB0" in captured["url"]
    assert "oembed" in captured["url"]
    assert meta.title == "Sample YouTube Video"
    assert meta.author_name == "Sample Channel"
    assert meta.thumbnail_url.startswith("https://i.ytimg.com/")


def test_fetch_oembed_retries_on_5xx(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def fake_get(url: str, *, timeout: float = 10.0) -> _FakeResp:
        calls["n"] += 1
        if calls["n"] == 1:
            return _FakeResp(status_code=503)
        return _FakeResp(text=json.dumps(_SAMPLE_OEMBED))

    monkeypatch.setattr(youtube, "_http_get", fake_get)
    monkeypatch.setattr(youtube.time, "sleep", lambda _s: None)
    meta = youtube._fetch_oembed("tj8ggd8UvB0")
    assert meta.title == "Sample YouTube Video"
    assert calls["n"] == 2


def test_fetch_oembed_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        youtube, "_http_get", lambda url, *, timeout=10.0: _FakeResp(status_code=503)
    )
    monkeypatch.setattr(youtube.time, "sleep", lambda _s: None)
    with pytest.raises(notecraft.NotecraftError):
        youtube._fetch_oembed("tj8ggd8UvB0")


def test_fetch_oembed_404_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deleted / private videos return 404 — not retryable, must raise."""
    monkeypatch.setattr(
        youtube, "_http_get", lambda url, *, timeout=10.0: _FakeResp(status_code=404)
    )
    with pytest.raises(notecraft.NotecraftError) as exc:
        youtube._fetch_oembed("aaaaaaaaaaa")
    assert "404" in str(exc.value)


def test_fetch_oembed_malformed_json_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """200 status but garbage body — not JSON — must raise."""
    monkeypatch.setattr(
        youtube, "_http_get", lambda url, *, timeout=10.0: _FakeResp(text="<html>not json</html>")
    )
    with pytest.raises(notecraft.NotecraftError):
        youtube._fetch_oembed("tj8ggd8UvB0")


# ---------- transcript download ----------

class _FakeSnippet:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeFetched:
    def __init__(self, texts: list[str]) -> None:
        self._snips = [_FakeSnippet(t) for t in texts]

    def __iter__(self):
        return iter(self._snips)


def test_download_transcript_writes_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_fetch(self, video_id, languages=None, **kwargs):
        return _FakeFetched(["hello", "world"])

    from youtube_transcript_api import YouTubeTranscriptApi

    monkeypatch.setattr(YouTubeTranscriptApi, "fetch", fake_fetch, raising=True)
    monkeypatch.setattr(youtube, "_assets_youtube_dir", lambda *_a, **_kw: tmp_path)

    out = youtube._download_transcript("tj8ggd8UvB0", tmp_path)
    assert out is not None
    assert out == tmp_path / "tj8ggd8UvB0.txt"
    assert out.read_text(encoding="utf-8") == "hello\nworld"


def test_download_transcript_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "tj8ggd8UvB0.txt"
    target.write_text("already here", encoding="utf-8")

    def fail_fetch(self, video_id, languages=None, **kwargs):
        raise AssertionError("should not refetch when file exists")

    from youtube_transcript_api import YouTubeTranscriptApi

    monkeypatch.setattr(YouTubeTranscriptApi, "fetch", fail_fetch, raising=True)
    monkeypatch.setattr(youtube, "_assets_youtube_dir", lambda *_a, **_kw: tmp_path)

    out = youtube._download_transcript("tj8ggd8UvB0", tmp_path)
    assert out == target
    assert out.read_text(encoding="utf-8") == "already here"


def test_download_transcript_atomic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Write to .tmp then os.replace — no partial file on the final path during a write."""
    seen_during_write: list[bool] = []

    def fake_fetch(self, video_id, languages=None, **kwargs):
        seen_during_write.append((tmp_path / "tj8ggd8UvB0.txt").exists())
        return _FakeFetched(["partial-then-final"])

    from youtube_transcript_api import YouTubeTranscriptApi

    monkeypatch.setattr(YouTubeTranscriptApi, "fetch", fake_fetch, raising=True)
    monkeypatch.setattr(youtube, "_assets_youtube_dir", lambda *_a, **_kw: tmp_path)

    out = youtube._download_transcript("tj8ggd8UvB0", tmp_path)
    assert out is not None
    assert seen_during_write == [False]
    assert not (tmp_path / "tj8ggd8UvB0.txt.tmp").exists()


def test_download_transcript_disabled_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._errors import TranscriptsDisabled

    def fake_fetch(self, video_id, languages=None, **kwargs):
        raise TranscriptsDisabled(video_id)

    monkeypatch.setattr(YouTubeTranscriptApi, "fetch", fake_fetch, raising=True)
    monkeypatch.setattr(youtube, "_assets_youtube_dir", lambda *_a, **_kw: tmp_path)

    out = youtube._download_transcript("tj8ggd8UvB0", tmp_path)
    assert out is None
    assert not (tmp_path / "tj8ggd8UvB0.txt").exists()


def test_download_transcript_unavailable_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._errors import VideoUnavailable

    def fake_fetch(self, video_id, languages=None, **kwargs):
        raise VideoUnavailable(video_id)

    monkeypatch.setattr(YouTubeTranscriptApi, "fetch", fake_fetch, raising=True)
    monkeypatch.setattr(youtube, "_assets_youtube_dir", lambda *_a, **_kw: tmp_path)

    with pytest.raises(notecraft.NotecraftError):
        youtube._download_transcript("tj8ggd8UvB0", tmp_path)


def test_download_transcript_empty_text_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """All snippets empty / whitespace → no file written, return None."""
    from youtube_transcript_api import YouTubeTranscriptApi

    monkeypatch.setattr(
        YouTubeTranscriptApi,
        "fetch",
        lambda self, video_id, languages=None, **kwargs: _FakeFetched(["  ", "", "\n"]),
        raising=True,
    )
    monkeypatch.setattr(youtube, "_assets_youtube_dir", lambda *_a, **_kw: tmp_path)

    out = youtube._download_transcript("tj8ggd8UvB0", tmp_path)
    assert out is None
    assert not (tmp_path / "tj8ggd8UvB0.txt").exists()


def test_download_transcript_passes_languages_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Languages tuple passed by caller must reach the underlying fetch() call."""
    captured: dict[str, Any] = {}

    def fake_fetch(self, video_id, languages=None, **kwargs):
        captured["languages"] = tuple(languages) if languages else None
        return _FakeFetched(["x"])

    from youtube_transcript_api import YouTubeTranscriptApi

    monkeypatch.setattr(YouTubeTranscriptApi, "fetch", fake_fetch, raising=True)
    monkeypatch.setattr(youtube, "_assets_youtube_dir", lambda *_a, **_kw: tmp_path)

    youtube._download_transcript("tj8ggd8UvB0", tmp_path, languages=("ja", "en"))
    assert captured["languages"] == ("ja", "en")


# ---------- transcript language priority (frontmatter `language:`) ----------


def test_transcript_language_priority_default_when_unset(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    note = _make_note(vault, "title: T\n")
    assert youtube._transcript_language_priority(note) == ("zh-Hans", "zh-Hant", "zh", "en")


def test_transcript_language_priority_zh_expands(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    note = _make_note(vault, "title: T\nlanguage: zh\n")
    assert youtube._transcript_language_priority(note) == ("zh-Hans", "zh-Hant", "zh", "en")


def test_transcript_language_priority_en_only(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    note = _make_note(vault, "title: T\nlanguage: en\n")
    assert youtube._transcript_language_priority(note) == ("en",)


def test_transcript_language_priority_other_with_en_fallback(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    note = _make_note(vault, "title: T\nlanguage: ja\n")
    assert youtube._transcript_language_priority(note) == ("ja", "en")


# ---------- end-to-end run() ----------

def _patch_run(
    monkeypatch: pytest.MonkeyPatch,
    *,
    tx_dir: Path,
    transcript_texts: list[str] | None = None,
    transcript_exc: Exception | None = None,
) -> None:
    monkeypatch.setattr(
        youtube,
        "_http_get",
        lambda url, *, timeout=10.0: _FakeResp(text=json.dumps(_SAMPLE_OEMBED)),
    )
    monkeypatch.setattr(youtube, "_assets_youtube_dir", lambda *_a, **_kw: tx_dir)

    from youtube_transcript_api import YouTubeTranscriptApi

    def fake_fetch(self, video_id, languages=None, **kwargs):
        if transcript_exc is not None:
            raise transcript_exc
        return _FakeFetched(transcript_texts or [])

    monkeypatch.setattr(YouTubeTranscriptApi, "fetch", fake_fetch, raising=True)


def test_run_writeback_full(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = _make_vault(tmp_path)
    tx_dir = vault / "assets" / "youtube"
    tx_dir.mkdir(parents=True, exist_ok=True)
    _patch_run(monkeypatch, tx_dir=tx_dir, transcript_texts=["hello", "world"])

    note = _make_note(
        vault,
        "title: 'youtube:tj8ggd8UvB0'\nsource: https://www.youtube.com/watch?v=tj8ggd8UvB0\n",
    )
    out = youtube.run(note, arg=None)
    assert out["youtube_transcript"] == tx_dir / "tj8ggd8UvB0.txt"

    reloaded = Note(note.path)
    md = reloaded._post.metadata
    assert md["title"] == "Sample YouTube Video"
    assert md["youtube_id"] == "tj8ggd8UvB0"
    assert md["source"] == "https://www.youtube.com/watch?v=tj8ggd8UvB0"
    assert md["youtube_author"] == "Sample Channel"
    assert md["source_file"] == "assets/youtube/tj8ggd8UvB0.txt"


def test_run_no_transcript_still_writes_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _make_vault(tmp_path)
    tx_dir = vault / "assets" / "youtube"
    tx_dir.mkdir(parents=True, exist_ok=True)

    from youtube_transcript_api._errors import TranscriptsDisabled

    _patch_run(
        monkeypatch,
        tx_dir=tx_dir,
        transcript_exc=TranscriptsDisabled("tj8ggd8UvB0"),
    )

    note = _make_note(
        vault,
        "title: 'youtube:tj8ggd8UvB0'\nsource: https://www.youtube.com/watch?v=tj8ggd8UvB0\n",
    )
    out = youtube.run(note, arg=None)
    assert out == {}

    reloaded = Note(note.path)
    md = reloaded._post.metadata
    assert md["youtube_id"] == "tj8ggd8UvB0"
    assert md["title"] == "Sample YouTube Video"  # stub-form title gets replaced
    # source_file must NOT be set when transcript missing
    assert "source_file" not in md or not md.get("source_file")


def test_run_preserves_user_title(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = _make_vault(tmp_path)
    tx_dir = vault / "assets" / "youtube"
    tx_dir.mkdir(parents=True, exist_ok=True)
    _patch_run(monkeypatch, tx_dir=tx_dir, transcript_texts=["hi"])

    note = _make_note(
        vault,
        "title: 'My personal summary'\nsource: https://www.youtube.com/watch?v=tj8ggd8UvB0\n",
    )
    youtube.run(note, arg=None)
    reloaded = Note(note.path)
    assert reloaded._post.metadata["title"] == "My personal summary"


@pytest.mark.parametrize("stub_form", ["youtube:tj8ggd8UvB0", "tj8ggd8UvB0", "", "  "])
def test_run_replaces_stub_titles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_form: str
) -> None:
    vault = _make_vault(tmp_path)
    tx_dir = vault / "assets" / "youtube"
    tx_dir.mkdir(parents=True, exist_ok=True)
    _patch_run(monkeypatch, tx_dir=tx_dir, transcript_texts=["hi"])

    note = _make_note(
        vault,
        f"title: '{stub_form}'\nsource: https://www.youtube.com/watch?v=tj8ggd8UvB0\n",
    )
    youtube.run(note, arg=None)
    reloaded = Note(note.path)
    assert reloaded._post.metadata["title"] == "Sample YouTube Video"


def test_run_arg_overrides_frontmatter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _make_vault(tmp_path)
    tx_dir = vault / "assets" / "youtube"
    tx_dir.mkdir(parents=True, exist_ok=True)
    _patch_run(monkeypatch, tx_dir=tx_dir, transcript_texts=["x"])

    note = _make_note(vault, "title: stub\nyoutube_id: aaaaaaaaaaa\n")
    out = youtube.run(note, arg="https://youtu.be/tj8ggd8UvB0")
    assert out["youtube_transcript"].name == "tj8ggd8UvB0.txt"


# ---------- registry ----------

def test_youtube_registered() -> None:
    from llmwiki.tasks import TASK_REGISTRY
    assert "youtube" in TASK_REGISTRY


# ---------- watcher path E2E ----------

def test_watcher_dispatches_youtube_and_keeps_in_raw(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Note with task/youtube tag → watcher runs ingest → note stays in raw/, tag removed, status=done."""
    from llmwiki.label_watcher import LabelWatcher
    from llmwiki.vault import Vault

    vault_root = _make_vault(tmp_path)
    tx_dir = vault_root / "assets" / "youtube"
    tx_dir.mkdir(parents=True, exist_ok=True)

    _patch_run(monkeypatch, tx_dir=tx_dir, transcript_texts=["hello"])

    note_path = vault_root / "raw" / "in.md"
    note_path.write_text(
        "---\n"
        "title: stub\n"
        "youtube_id: tj8ggd8UvB0\n"
        "tags: [task/youtube]\n"
        "status: pending\n"
        "---\nbody\n",
        encoding="utf-8",
    )

    watcher = LabelWatcher(Vault(root=vault_root))
    watcher.scan_once()

    assert note_path.is_file()
    assert not (vault_root / "wiki" / "in.md").exists()

    reloaded = Note(note_path)
    assert "task/youtube" not in reloaded.tags
    assert reloaded.status == "done"
    assert reloaded._post.metadata["youtube_id"] == "tj8ggd8UvB0"
    assert reloaded._post.metadata["source_file"] == "assets/youtube/tj8ggd8UvB0.txt"
    assert (tx_dir / "tj8ggd8UvB0.txt").is_file()
