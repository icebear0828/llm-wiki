from __future__ import annotations

import json
from pathlib import Path

from llmwiki.vault import Note, SourceManifest, SourceRecord, Vault, source_record_from_note


def _vault(tmp_path: Path) -> Vault:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "raw").mkdir()
    (tmp_path / "wiki").mkdir()
    (tmp_path / "assets").mkdir()
    return Vault(root=tmp_path)


def _write_note(vault: Vault, relpath: str, frontmatter: str, body: str = "body\n") -> Note:
    path = vault.root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{frontmatter}---\n{body}", encoding="utf-8")
    return Note(path)


def test_source_manifest_round_trips_added_records(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    manifest = SourceManifest(vault)
    manifest.upsert(
        SourceRecord(
            workspace_key="topics/ai-agents",
            notebook_id="nb-topic",
            source_ref="assets/arxiv/2401.12345.pdf",
            source_type="arxiv",
            local_path="raw/arxiv-2401.12345.md",
            added_at="2026-05-16T10:00:00Z",
            status="added",
            title="Paper",
            source_url="https://arxiv.org/abs/2401.12345",
            source_file="assets/arxiv/2401.12345.pdf",
            artifact_paths=("assets/report/paper.md",),
        )
    )
    manifest.save()

    raw = json.loads((vault.root / ".llmwiki" / "sources.json").read_text())
    assert raw["_schema_version"] == 1
    assert raw["sources"][0]["workspace_key"] == "topics/ai-agents"

    fresh = SourceManifest(vault)
    record = fresh.find_added(
        workspace_key="topics/ai-agents",
        notebook_id="nb-topic",
        source_ref="assets/arxiv/2401.12345.pdf",
    )

    assert record is not None
    assert record.source_type == "arxiv"
    assert record.local_path == "raw/arxiv-2401.12345.md"
    assert record.artifact_paths == ("assets/report/paper.md",)


def test_source_record_from_note_prefers_local_pdf_for_arxiv(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    (vault.root / "assets" / "arxiv").mkdir()
    (vault.root / "assets" / "arxiv" / "2401.12345.pdf").write_bytes(b"%PDF")
    note = _write_note(
        vault,
        "raw/arxiv-2401.12345.md",
        "title: Paper\n"
        "source: https://arxiv.org/abs/2401.12345\n"
        "source_file: assets/arxiv/2401.12345.pdf\n"
        "arxiv_id: '2401.12345'\n",
    )

    record = source_record_from_note(
        note,
        vault,
        workspace_key="topics/papers",
        notebook_id="nb-papers",
        added_at="2026-05-16T10:00:00Z",
    )

    assert record.workspace_key == "topics/papers"
    assert record.notebook_id == "nb-papers"
    assert record.source_ref == "assets/arxiv/2401.12345.pdf"
    assert record.source_type == "arxiv"
    assert record.local_path == "raw/arxiv-2401.12345.md"
    assert record.source_url == "https://arxiv.org/abs/2401.12345"
    assert record.source_file == "assets/arxiv/2401.12345.pdf"


def test_source_record_from_note_uses_note_body_when_no_source(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    note = _write_note(vault, "raw/local.md", "title: Local Note\n")

    record = source_record_from_note(
        note,
        vault,
        workspace_key="raw/local.md",
        notebook_id="nb-local",
        added_at="2026-05-16T10:00:00Z",
    )

    assert record.source_ref == "raw/local.md"
    assert record.source_type == "local-note"
    assert record.local_path == "raw/local.md"
