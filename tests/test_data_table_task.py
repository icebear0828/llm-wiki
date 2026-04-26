from __future__ import annotations

from pathlib import Path

import pytest

from llmwiki import notecraft
from llmwiki.tasks import data_table
from llmwiki.vault import Note


def _make_note(tmp_path: Path, frontmatter: str, body: str = "hi\n") -> Note:
    p = tmp_path / "n.md"
    p.write_text(f"---\n{frontmatter}---\n{body}", encoding="utf-8")
    return Note(p)


def _patch_run(
    monkeypatch: pytest.MonkeyPatch, captured: dict[str, object]
) -> None:
    def fake(
        cmd,
        *,
        source,
        out_dir,
        extra_args=None,
        timeout=600.0,
        subcommand=None,
        expect_artifact=True,
    ):
        captured["cmd"] = cmd
        captured["source"] = source
        captured["out_dir"] = out_dir
        captured["extra_args"] = list(extra_args or [])
        return out_dir / "table.csv"

    monkeypatch.setattr(notecraft, "run", fake)
    monkeypatch.setattr(data_table.notecraft, "run", fake, raising=True)


def test_data_table_passes_instructions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}
    _patch_run(monkeypatch, captured)
    note = _make_note(
        tmp_path,
        "title: T\ntags: ['task/data-table']\nsource: https://x\n"
        "data_table_instructions: 'Compare A vs B by year'\nstatus: pending\n",
    )

    result = data_table.run(note)
    assert "data-table" in result
    assert captured["cmd"] == "data-table"
    assert captured["extra_args"] == ["--instructions", "Compare A vs B by year"]
    out_dir = captured["out_dir"]
    assert isinstance(out_dir, Path)
    assert out_dir.parts[-2:] == ("assets", "data-table")


def test_data_table_missing_instructions_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}
    _patch_run(monkeypatch, captured)
    note = _make_note(
        tmp_path,
        "title: T\ntags: ['task/data-table']\nsource: https://x\nstatus: pending\n",
    )

    with pytest.raises(notecraft.NotecraftError):
        data_table.run(note)


def test_data_table_empty_instructions_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}
    _patch_run(monkeypatch, captured)
    note = _make_note(
        tmp_path,
        "title: T\ntags: ['task/data-table']\nsource: https://x\n"
        "data_table_instructions: '   '\nstatus: pending\n",
    )

    with pytest.raises(notecraft.NotecraftError):
        data_table.run(note)
