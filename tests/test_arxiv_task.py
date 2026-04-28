from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from llmwiki import notecraft
from llmwiki.tasks import arxiv
from llmwiki.vault import Note


_SAMPLE_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.12345v2</id>
    <title>Sample Paper Title  with Newlines
And Wrap</title>
    <summary>Abstract text here.
Spans lines.</summary>
    <published>2026-01-15T18:00:00Z</published>
    <author><name>Alice Q. Researcher</name></author>
    <author><name>Bob Builder</name></author>
  </entry>
</feed>
"""


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
        ("2401.12345", "2401.12345"),
        ("2401.12345v3", "2401.12345v3"),
        ("https://arxiv.org/abs/2401.12345", "2401.12345"),
        ("https://arxiv.org/abs/2401.12345v2", "2401.12345v2"),
        ("https://arxiv.org/pdf/2401.12345v2.pdf", "2401.12345v2"),
        ("http://arxiv.org/pdf/2310.06825.pdf", "2310.06825"),
        ("arxiv:2401.12345", "2401.12345"),
        ("arXiv:2401.12345v1", "2401.12345v1"),
        ("cs/0701001", "cs/0701001"),
        ("https://arxiv.org/abs/cs.AI/0701001", "cs.AI/0701001"),
    ],
)
def test_parse_arxiv_id(raw: str, expected: str) -> None:
    assert arxiv._parse_arxiv_id(raw) == expected


def test_parse_arxiv_id_invalid_raises() -> None:
    with pytest.raises(notecraft.NotecraftError):
        arxiv._parse_arxiv_id("not an arxiv reference")


@pytest.mark.parametrize(
    "raw",
    [
        "random-2401.12345-string",      # `-` immediately before id: not a valid prefix
        "x2401.12345",                    # word char before
        "abc.2401.12345",                 # `.` before
        "2401.123456",                    # 6-digit suffix (overmatch trap)
        "2401.123",                       # too few digits
        "2401-12345",                     # wrong separator
    ],
)
def test_parse_arxiv_id_rejects_overmatch_and_garbage(raw: str) -> None:
    with pytest.raises(notecraft.NotecraftError):
        arxiv._parse_arxiv_id(raw)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("see paper 2401.12345 for context", "2401.12345"),  # space-prefixed: legit
        ("(2401.12345)", "2401.12345"),                       # paren-prefixed
        ("  2401.12345  ", "2401.12345"),                     # whitespace pad
    ],
)
def test_parse_arxiv_id_accepts_safe_prefixes(raw: str, expected: str) -> None:
    assert arxiv._parse_arxiv_id(raw) == expected


def test_strip_version_for_api() -> None:
    assert arxiv._strip_version("2401.12345v2") == "2401.12345"
    assert arxiv._strip_version("2401.12345") == "2401.12345"
    assert arxiv._strip_version("cs/0701001") == "cs/0701001"


# ---------- ID resolution priority ----------

def test_resolve_id_arg_wins(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    note = _make_note(vault, "title: T\narxiv_id: 2401.99999\nsource: https://arxiv.org/abs/2401.00000\n")
    assert arxiv._resolve_arxiv_id(note, "2401.12345") == "2401.12345"


def test_resolve_id_frontmatter_used(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    note = _make_note(vault, "title: T\narxiv_id: 2401.12345\n")
    assert arxiv._resolve_arxiv_id(note, None) == "2401.12345"


def test_resolve_id_from_source_url(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    note = _make_note(vault, "title: T\nsource: https://arxiv.org/abs/2310.06825\n")
    assert arxiv._resolve_arxiv_id(note, None) == "2310.06825"


def test_resolve_id_missing_raises(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    note = _make_note(vault, "title: T\n")
    with pytest.raises(notecraft.NotecraftError):
        arxiv._resolve_arxiv_id(note, None)


# ---------- metadata fetch ----------

class _FakeResp:
    def __init__(self, *, status_code: int = 200, text: str = "", content: bytes = b"") -> None:
        self.status_code = status_code
        self.text = text
        self.content = content

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


def test_fetch_metadata_parses_atom(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_get(url: str, *, timeout: float = 10.0) -> _FakeResp:
        captured["url"] = url
        return _FakeResp(text=_SAMPLE_ATOM)

    monkeypatch.setattr(arxiv, "_http_get", fake_get)
    meta = arxiv._fetch_metadata("2401.12345v2")
    assert "id_list=2401.12345" in captured["url"]
    assert meta.title == "Sample Paper Title with Newlines And Wrap"
    assert meta.abstract.strip() == "Abstract text here.\nSpans lines.".strip()
    assert meta.authors == ["Alice Q. Researcher", "Bob Builder"]
    assert meta.published.startswith("2026-01-15")


def test_fetch_metadata_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(arxiv, "_http_get", lambda url, *, timeout=10.0: _FakeResp(status_code=503))
    monkeypatch.setattr(arxiv.time, "sleep", lambda _s: None)
    with pytest.raises(notecraft.NotecraftError):
        arxiv._fetch_metadata("2401.12345")


# ---------- PDF download ----------

def test_download_pdf_writes_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_get(url: str, *, timeout: float = 60.0) -> _FakeResp:
        captured["url"] = url
        return _FakeResp(content=b"%PDF-1.7 fake")

    monkeypatch.setattr(arxiv, "_http_get_bytes", fake_get)
    monkeypatch.setattr(arxiv, "_assets_arxiv_dir", lambda *_a, **_kw: tmp_path)
    out = arxiv._download_pdf("2401.12345v2", tmp_path)
    assert out == tmp_path / "2401.12345v2.pdf"
    assert out.read_bytes() == b"%PDF-1.7 fake"
    assert "2401.12345v2.pdf" in captured["url"]


def test_download_pdf_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "2401.12345.pdf"
    target.write_bytes(b"%PDF-1.7 already here")  # valid magic → idempotent

    def fail_get(url: str, *, timeout: float = 60.0) -> _FakeResp:
        raise AssertionError("should not refetch when valid PDF exists")

    monkeypatch.setattr(arxiv, "_http_get_bytes", fail_get)
    monkeypatch.setattr(arxiv, "_assets_arxiv_dir", lambda *_a, **_kw: tmp_path)
    out = arxiv._download_pdf("2401.12345", tmp_path)
    assert out == target
    assert out.read_bytes() == b"%PDF-1.7 already here"


def test_download_pdf_old_id_replaces_slash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(arxiv, "_http_get_bytes", lambda url, *, timeout=60.0: _FakeResp(content=b"x"))
    monkeypatch.setattr(arxiv, "_assets_arxiv_dir", lambda *_a, **_kw: tmp_path)
    out = arxiv._download_pdf("cs/0701001", tmp_path)
    assert out.name == "cs_0701001.pdf"
    assert out.exists()


# ---------- end-to-end run() ----------

def test_run_writeback_full(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = _make_vault(tmp_path)
    pdf_dir = vault / "assets" / "arxiv"
    pdf_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(arxiv, "_http_get", lambda url, *, timeout=10.0: _FakeResp(text=_SAMPLE_ATOM))
    monkeypatch.setattr(
        arxiv, "_http_get_bytes", lambda url, *, timeout=60.0: _FakeResp(content=b"%PDF-1.7")
    )
    monkeypatch.setattr(arxiv, "_assets_arxiv_dir", lambda *_a, **_kw: pdf_dir)

    note = _make_note(vault, "title: 'arxiv:2401.12345v2'\nsource: https://arxiv.org/abs/2401.12345v2\n")
    out = arxiv.run(note, arg=None)
    assert out["arxiv_pdf"] == pdf_dir / "2401.12345v2.pdf"
    assert (pdf_dir / "2401.12345v2.pdf").read_bytes() == b"%PDF-1.7"

    reloaded = Note(note.path)
    assert reloaded._post.metadata["title"] == "Sample Paper Title with Newlines And Wrap"
    assert reloaded._post.metadata["arxiv_id"] == "2401.12345v2"
    assert reloaded._post.metadata["source"] == "https://arxiv.org/abs/2401.12345v2"
    assert reloaded._post.metadata["source_file"] == "assets/arxiv/2401.12345v2.pdf"
    assert reloaded._post.metadata["arxiv_authors"] == ["Alice Q. Researcher", "Bob Builder"]
    assert str(reloaded._post.metadata["arxiv_published"]).startswith("2026-01-15")
    assert "Abstract text here." in reloaded.body


def test_run_preserves_user_title(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = _make_vault(tmp_path)
    pdf_dir = vault / "assets" / "arxiv"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(arxiv, "_http_get", lambda url, *, timeout=10.0: _FakeResp(text=_SAMPLE_ATOM))
    monkeypatch.setattr(arxiv, "_http_get_bytes", lambda url, *, timeout=60.0: _FakeResp(content=b"%PDF-1.7"))
    monkeypatch.setattr(arxiv, "_assets_arxiv_dir", lambda *_a, **_kw: pdf_dir)

    note = _make_note(vault, "title: 'My personal summary'\nsource: https://arxiv.org/abs/2401.12345v2\n")
    arxiv.run(note, arg=None)
    reloaded = Note(note.path)
    # User-provided title MUST be preserved over arxiv-fetched one
    assert reloaded._post.metadata["title"] == "My personal summary"


@pytest.mark.parametrize("stub_form", ["arxiv:2401.12345v2", "2401.12345v2", "", "  "])
def test_run_replaces_stub_titles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_form: str
) -> None:
    vault = _make_vault(tmp_path)
    pdf_dir = vault / "assets" / "arxiv"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(arxiv, "_http_get", lambda url, *, timeout=10.0: _FakeResp(text=_SAMPLE_ATOM))
    monkeypatch.setattr(arxiv, "_http_get_bytes", lambda url, *, timeout=60.0: _FakeResp(content=b"%PDF"))
    monkeypatch.setattr(arxiv, "_assets_arxiv_dir", lambda *_a, **_kw: pdf_dir)

    note = _make_note(vault, f"title: '{stub_form}'\nsource: https://arxiv.org/abs/2401.12345v2\n")
    arxiv.run(note, arg=None)
    reloaded = Note(note.path)
    assert reloaded._post.metadata["title"] == "Sample Paper Title with Newlines And Wrap"


def test_download_pdf_atomic_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """write to .tmp then os.replace — no partial file on the final path during a write."""
    seen_during_write: list[bool] = []

    def fake_get(url: str, *, timeout: float = 60.0) -> _FakeResp:
        # snapshot whether the final file exists before this call returns
        seen_during_write.append((tmp_path / "2401.12345.pdf").exists())
        return _FakeResp(content=b"%PDF-1.7 good")

    monkeypatch.setattr(arxiv, "_http_get_bytes", fake_get)
    monkeypatch.setattr(arxiv, "_assets_arxiv_dir", lambda *_a, **_kw: tmp_path)
    out = arxiv._download_pdf("2401.12345", tmp_path)
    assert out.read_bytes() == b"%PDF-1.7 good"
    assert seen_during_write == [False]
    # No leftover .tmp file
    assert not (tmp_path / "2401.12345.pdf.tmp").exists()


def test_download_pdf_rejects_existing_corrupt_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Existing file without %PDF magic → re-download (not a silently-corrupt skip)."""
    bad = tmp_path / "2401.12345.pdf"
    bad.write_bytes(b"not a pdf at all")

    monkeypatch.setattr(
        arxiv, "_http_get_bytes", lambda url, *, timeout=60.0: _FakeResp(content=b"%PDF-1.7 good")
    )
    monkeypatch.setattr(arxiv, "_assets_arxiv_dir", lambda *_a, **_kw: tmp_path)
    out = arxiv._download_pdf("2401.12345", tmp_path)
    assert out.read_bytes() == b"%PDF-1.7 good"


def test_fetch_metadata_retries_on_5xx(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def fake_get(url: str, *, timeout: float = 10.0) -> _FakeResp:
        calls["n"] += 1
        if calls["n"] == 1:
            return _FakeResp(status_code=503)
        return _FakeResp(text=_SAMPLE_ATOM)

    monkeypatch.setattr(arxiv, "_http_get", fake_get)
    monkeypatch.setattr(arxiv.time, "sleep", lambda _s: None)
    meta = arxiv._fetch_metadata("2401.12345")
    assert meta.title.startswith("Sample Paper Title")
    assert calls["n"] == 2


def test_run_arg_overrides_frontmatter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = _make_vault(tmp_path)
    pdf_dir = vault / "assets" / "arxiv"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(arxiv, "_http_get", lambda url, *, timeout=10.0: _FakeResp(text=_SAMPLE_ATOM))
    monkeypatch.setattr(
        arxiv, "_http_get_bytes", lambda url, *, timeout=60.0: _FakeResp(content=b"x")
    )
    monkeypatch.setattr(arxiv, "_assets_arxiv_dir", lambda *_a, **_kw: pdf_dir)

    note = _make_note(vault, "title: stub\narxiv_id: 9999.99999\n")
    out = arxiv.run(note, arg="https://arxiv.org/abs/2401.12345v2")
    assert out["arxiv_pdf"].name == "2401.12345v2.pdf"


# ---------- registry ----------

def test_arxiv_registered() -> None:
    from llmwiki.tasks import TASK_REGISTRY
    assert "arxiv" in TASK_REGISTRY


# ---------- watcher path E2E ----------

def test_watcher_dispatches_arxiv_and_keeps_in_raw(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Note with task/arxiv tag → watcher runs ingest → note stays in raw/, tag removed, status=done."""
    from llmwiki.label_watcher import LabelWatcher
    from llmwiki.vault import Vault

    vault_root = _make_vault(tmp_path)
    pdf_dir = vault_root / "assets" / "arxiv"
    pdf_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(arxiv, "_http_get", lambda url, *, timeout=10.0: _FakeResp(text=_SAMPLE_ATOM))
    monkeypatch.setattr(
        arxiv, "_http_get_bytes", lambda url, *, timeout=60.0: _FakeResp(content=b"%PDF-1.7")
    )

    note_path = vault_root / "raw" / "in.md"
    note_path.write_text(
        "---\n"
        "title: stub\n"
        "arxiv_id: '2401.12345v2'\n"
        "tags: [task/arxiv]\n"
        "status: pending\n"
        "---\nbody\n",
        encoding="utf-8",
    )

    watcher = LabelWatcher(Vault(root=vault_root))
    watcher.scan_once()

    # Note stayed in raw/ (not moved to wiki/)
    assert note_path.is_file()
    assert not (vault_root / "wiki" / "in.md").exists()

    reloaded = Note(note_path)
    # task/arxiv tag was removed by watcher's stay_in_raw_tasks block
    assert "task/arxiv" not in reloaded.tags
    assert reloaded.status == "done"
    # arxiv ingest writeback occurred
    assert reloaded._post.metadata["arxiv_id"] == "2401.12345v2"
    assert reloaded._post.metadata["source_file"] == "assets/arxiv/2401.12345v2.pdf"
    assert (pdf_dir / "2401.12345v2.pdf").is_file()
