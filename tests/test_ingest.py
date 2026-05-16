from __future__ import annotations

import logging
from pathlib import Path

import pytest

from llmwiki import ingest
from llmwiki.ingest import IngestConflict, move_to_wiki
from llmwiki.vault import Note, NotebookIndex, SourceManifest, SourceRecord, Vault


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "raw").mkdir()
    (tmp_path / "wiki").mkdir()
    (tmp_path / "assets" / "audio").mkdir(parents=True)
    return Vault(root=tmp_path)


def _make_raw_note(vault: Vault, name: str = "foo.md") -> Note:
    p = vault.raw / name
    p.write_text(
        "---\ntitle: Foo\ntags:\n  - task/audio\nstatus: pending\n---\noriginal body\n",
        encoding="utf-8",
    )
    return Note(p)


def _make_artifact(vault: Vault, kind: str, name: str) -> Path:
    art = vault.assets / kind / name
    art.parent.mkdir(parents=True, exist_ok=True)
    art.write_bytes(b"x")
    return art


def test_move_to_wiki_happy(vault: Vault) -> None:
    note = _make_raw_note(vault)
    art = _make_artifact(vault, "audio", "foo.mp3")
    new_note = move_to_wiki(note, vault, {"audio": art})
    assert new_note.path == vault.wiki / "foo.md"
    assert not (vault.raw / "foo.md").exists()
    assert new_note.status == "done"
    assert new_note.artifacts["audio"] == Path("assets/audio/foo.mp3")
    body = new_note.body
    assert body.splitlines()[0] == "![[assets/audio/foo.mp3]]"
    assert "original body" in body


def test_move_to_wiki_idempotent_in_wiki(vault: Vault) -> None:
    note = _make_raw_note(vault)
    art = _make_artifact(vault, "audio", "foo.mp3")
    n1 = move_to_wiki(note, vault, {"audio": art})
    n2 = move_to_wiki(n1, vault, {"audio": art})
    body = n2.body
    assert body.count("![[assets/audio/foo.mp3]]") == 1
    assert (vault.wiki / "foo.md").exists()


def test_move_to_wiki_no_tmp_leftover(vault: Vault) -> None:
    note = _make_raw_note(vault)
    art = _make_artifact(vault, "audio", "foo.mp3")
    move_to_wiki(note, vault, {"audio": art})
    leftover = list(vault.root.glob("**/*.tmp"))
    assert leftover == []


def test_move_to_wiki_same_name_conflict_raises_and_keeps_raw(vault: Vault) -> None:
    existing = vault.wiki / "foo.md"
    existing.write_text(
        "---\ntitle: Curated\nstatus: done\n---\nimportant curated content\n",
        encoding="utf-8",
    )
    note = _make_raw_note(vault)
    art = _make_artifact(vault, "audio", "foo.mp3")

    with pytest.raises(IngestConflict) as exc_info:
        move_to_wiki(note, vault, {"audio": art})

    assert "foo.md" in str(exc_info.value)
    assert (vault.raw / "foo.md").exists()
    assert "important curated content" in existing.read_text(encoding="utf-8")
    assert list(vault.root.glob("**/*.tmp")) == []


def test_move_to_wiki_conflict_happens_before_r2_upload(
    vault: Vault, monkeypatch: pytest.MonkeyPatch
) -> None:
    (vault.root / "r2.toml").write_text(
        """
[r2]
enabled = true
endpoint = "https://x.r2.cloudflarestorage.com"
access_key = "k"
secret_key = "s"
bucket = "b"
custom_domain = "https://pub.example.com"
""",
        encoding="utf-8",
    )
    (vault.wiki / "foo.md").write_text(
        "---\ntitle: Curated\nstatus: done\n---\ncurated\n",
        encoding="utf-8",
    )
    note = _make_raw_note(vault)
    art = _make_artifact(vault, "audio", "foo.mp3")

    def unexpected_upload(_cfg: object, _path: Path, _root: Path) -> str:
        pytest.fail("R2 upload must not run when ingest destination conflicts")

    monkeypatch.setattr(ingest, "upload_asset", unexpected_upload)

    with pytest.raises(IngestConflict):
        move_to_wiki(note, vault, {"audio": art})

    assert art.exists()
    assert (vault.raw / "foo.md").exists()
    assert (vault.wiki / "foo.md").read_text(encoding="utf-8").endswith("curated\n")


def test_move_to_wiki_unlink_failure_does_not_lose_data(
    vault: Vault, monkeypatch: pytest.MonkeyPatch
) -> None:
    note = _make_raw_note(vault)
    art = _make_artifact(vault, "audio", "foo.mp3")
    raw_path = note.path
    real_unlink = Path.unlink

    def boom_unlink(self: Path, *args: object, **kwargs: object) -> None:
        if self == raw_path:
            raise OSError("simulated crash after dest write")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", boom_unlink)

    with pytest.raises(OSError):
        move_to_wiki(note, vault, {"audio": art})

    assert (vault.wiki / "foo.md").exists()
    assert (vault.raw / "foo.md").exists()


def test_move_to_wiki_fsync_path_does_not_crash(vault: Vault) -> None:
    note = _make_raw_note(vault)
    art = _make_artifact(vault, "audio", "foo.mp3")
    new_note = move_to_wiki(note, vault, {"audio": art})
    assert new_note.path.exists()


def test_move_to_wiki_rekeys_notebook_index(vault: Vault) -> None:
    note = _make_raw_note(vault)
    idx = NotebookIndex(vault)
    idx.set("raw/foo.md", "nb-keep")
    idx.save()

    art = _make_artifact(vault, "audio", "foo.mp3")
    move_to_wiki(note, vault, {"audio": art})

    fresh = NotebookIndex(vault)
    assert fresh.get("raw/foo.md") is None
    assert fresh.get("wiki/foo.md") == "nb-keep"


def test_move_to_wiki_rekeys_source_manifest(vault: Vault) -> None:
    note = _make_raw_note(vault)
    manifest = SourceManifest(vault)
    manifest.upsert(
        SourceRecord(
            workspace_key="raw/foo.md",
            notebook_id="nb-keep",
            source_ref="raw/foo.md",
            source_type="local-note",
            local_path="raw/foo.md",
            added_at="2026-05-16T10:00:00Z",
            status="added",
            title="Foo",
        )
    )
    manifest.save()

    art = _make_artifact(vault, "audio", "foo.mp3")
    move_to_wiki(note, vault, {"audio": art})

    fresh = SourceManifest(vault)
    assert fresh.find_added(
        workspace_key="raw/foo.md",
        notebook_id="nb-keep",
        source_ref="raw/foo.md",
    ) is None
    record = fresh.find_added(
        workspace_key="wiki/foo.md",
        notebook_id="nb-keep",
        source_ref="wiki/foo.md",
    )
    assert record is not None
    assert record.local_path == "wiki/foo.md"
    assert record.artifact_paths == ("assets/audio/foo.mp3",)


def test_move_to_wiki_leaves_unrelated_same_stem_index_key(vault: Vault) -> None:
    note = _make_raw_note(vault)
    idx = NotebookIndex(vault)
    idx.set("raw/foo.md", "nb-raw")
    idx.set("wiki/sub/foo.md", "nb-other-foo")
    idx.save()

    art = _make_artifact(vault, "audio", "foo.mp3")
    move_to_wiki(note, vault, {"audio": art})

    fresh = NotebookIndex(vault)
    assert fresh.get("raw/foo.md") is None
    assert fresh.get("wiki/foo.md") == "nb-raw"
    assert fresh.get("wiki/sub/foo.md") == "nb-other-foo"


def test_move_to_wiki_keeps_local_file_when_r2_fails(
    vault: Vault,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    (vault.root / "r2.toml").write_text(
        """
[r2]
enabled = true
endpoint = "https://x.r2.cloudflarestorage.com"
access_key = "k"
secret_key = "s"
bucket = "b"
custom_domain = "https://pub.example.com"
""",
        encoding="utf-8",
    )
    note = _make_raw_note(vault)
    art = _make_artifact(vault, "audio", "foo.mp3")

    class BotoLikeError(Exception):
        pass

    def boom_upload(_cfg: object, _path: Path, _root: Path) -> str:
        try:
            raise BotoLikeError("Signature=AKIA_LEAK secret_key=ABCDEF")
        except BotoLikeError as exc:
            from llmwiki.r2 import R2UploadError

            raise R2UploadError(
                f"upload failed bucket=b key=assets/audio/foo.mp3 "
                f"type={type(exc).__name__}"
            ) from None

    monkeypatch.setattr(ingest, "upload_asset", boom_upload)
    caplog.set_level(logging.ERROR, logger="llmwiki.ingest")

    new_note = move_to_wiki(note, vault, {"audio": art})

    assert art.exists()
    assert new_note.path == vault.wiki / "foo.md"
    assert "![[assets/audio/foo.mp3]]" in new_note.body

    formatter = logging.Formatter("%(levelname)s %(name)s %(message)s")
    for record in caplog.records:
        full = formatter.format(record)
        assert "Signature=" not in full
        assert "secret_key" not in full
        assert "AKIA_LEAK" not in full
