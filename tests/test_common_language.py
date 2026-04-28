from __future__ import annotations

from pathlib import Path

from llmwiki.tasks._common import language_from
from llmwiki.vault import Note


def _make_note(tmp_path: Path, frontmatter_body: str) -> Note:
    p = tmp_path / "n.md"
    p.write_text(f"---\n{frontmatter_body}---\nbody\n", encoding="utf-8")
    return Note(p)


def test_language_from_default_en(tmp_path: Path) -> None:
    note = _make_note(tmp_path, "title: T\n")
    assert language_from(note) == "en"


def test_language_from_explicit_default(tmp_path: Path) -> None:
    note = _make_note(tmp_path, "title: T\n")
    assert language_from(note, default="zh") == "zh"


def test_language_from_language_field(tmp_path: Path) -> None:
    note = _make_note(tmp_path, "title: T\nlanguage: zh\n")
    assert language_from(note) == "zh"


def test_language_from_lang_alias(tmp_path: Path) -> None:
    note = _make_note(tmp_path, "title: T\nlang: ja\n")
    assert language_from(note) == "ja"


def test_language_from_language_beats_lang(tmp_path: Path) -> None:
    note = _make_note(tmp_path, "title: T\nlanguage: en\nlang: zh\n")
    assert language_from(note) == "en"


def test_language_from_blank_string_falls_back(tmp_path: Path) -> None:
    note = _make_note(tmp_path, "title: T\nlanguage: '   '\n")
    assert language_from(note) == "en"


def test_language_from_non_string_falls_back(tmp_path: Path) -> None:
    note = _make_note(tmp_path, "title: T\nlanguage: 42\n")
    assert language_from(note) == "en"


def test_language_from_strips_whitespace(tmp_path: Path) -> None:
    note = _make_note(tmp_path, "title: T\nlanguage: '  fr  '\n")
    assert language_from(note) == "fr"
